# -*- coding: utf-8 -*-
#
#  Copyright 2015-2017 Ramil Nugmanov <stsouko@live.ru>
#  This file is part of ModelManager.
#
#  ModelManager is free software; you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
import json
import re
import requests
import subprocess as sp
from io import StringIO
from os import path
from CGRtools.CGRpreparer import CGRcombo
from CGRtools.files.RDFrw import RDFread, RDFwrite
from CGRtools.files import ReactionContainer, MoleculeContainer
from MODtools.config import MOLCONVERT
from ..utils import get_additives, chemax_post
from ..config import ModelType, ResultType, StructureType, StructureStatus


model_name = 'Preparer'


class Model(CGRcombo):
    def __init__(self):
        self.__workpath = '.'
        self.__additives = {x['name'].lower(): x for x in get_additives()}

        config_path = path.join(path.dirname(__file__), 'preparer')
        b_path = path.join(config_path, 'b_templates.rdf')
        m_path = path.join(config_path, 'm_templates.rdf')

        b_templates = open(b_path) if path.exists(b_path) else None
        m_templates = open(m_path) if path.exists(m_path) else None

        CGRcombo.__init__(self, cgr_type='0', extralabels=True, isotope=False, element=True, stereo=False,
                          b_templates=b_templates, m_templates=m_templates)

        with open(path.join(config_path, 'preparer.xml')) as f:
            self.__pre_rules = f.read()
        self.__pre_filter_chain = [dict(filter="standardizer",
                                        parameters=dict(standardizerDefinition=self.__pre_rules)),
                                   dict(filter="clean", parameters=dict(dim=2))]

        self.__post_rules = None
        self.__post_filter_chain = [dict(filter="clean", parameters=dict(dim=2))]
        if path.exists(path.join(config_path, 'postprocess.xml')):
            with open(path.join(config_path, 'postprocess.xml')) as f:
                self.__post_rules = f.read()
            self.__post_filter_chain.insert(0, dict(filter="standardizer",
                                                    parameters=dict(standardizerDefinition=self.__post_rules)))

    @staticmethod
    def get_example():
        return None

    @staticmethod
    def get_description():
        return 'Structure checking and possibly restoring'

    @staticmethod
    def get_name():
        return model_name

    @staticmethod
    def get_type():
        return ModelType.PREPARER

    def set_work_path(self, workpath):
        self.__workpath = workpath

    def get_results(self, structures):
        results = []
        for s in structures:
            if isinstance(s['data'], dict):  # AD-HOC for files processing
                if 'url' in s['data']:
                    results = self.__parsefile(s['data']['url'])
                break
            else:
                parsed = self.__parse_structure(s)
                if parsed:
                    results.append(parsed)
        return results

    def __parse_structure(self, structure):
        chemaxed = chemax_post('calculate/molExport',
                               dict(structure=structure['data'], parameters="rdf", filterChain=self.__pre_filter_chain))
        if not chemaxed:
            return False

        with StringIO(chemaxed['structure']) as in_file, StringIO() as out_file:
            try:
                result = self.__prepare(in_file, out_file)[0]
            except IndexError:
                return False
            prepared = out_file.getvalue()

        chemaxed = chemax_post('calculate/molExport',
                               dict(structure=prepared, parameters="mrv", filterChain=self.__post_filter_chain))
        if not chemaxed:
            return False

        return dict(data=chemaxed['structure'].split('\n')[1] + '\n', status=result['status'], type=result['type'],
                    results=result['results'])

    def __parsefile(self, url):
        r = requests.get(url)
        if r.status_code != 200:
            return False

        # ANY to MDL converter
        with sp.Popen([MOLCONVERT, 'rdf'], stdin=sp.PIPE, stdout=sp.PIPE,
                      stderr=sp.STDOUT, cwd=self.__workpath) as convert_mol:
            res = convert_mol.communicate(input=r.content)[0].decode()
            if convert_mol.returncode != 0:
                return False

        # MAGIC
        with StringIO(res) as mol_in, StringIO() as mol_out:
            report = self.__prepare(mol_in, mol_out, first_only=False)
            res = mol_out.getvalue()

        # MDL to MRV
        with sp.Popen([MOLCONVERT, 'mrv'], stdin=sp.PIPE, stdout=sp.PIPE,
                      stderr=sp.STDOUT, cwd=self.__workpath) as convert_mrv:
            res = convert_mrv.communicate(input=res.encode())[0].decode()
            if convert_mrv.returncode != 0:
                return False

        results = []
        with StringIO(res) as mrv:
            next(mrv)
            for n, (structure, tmp) in enumerate(zip(mrv, report), start=1):
                out = dict(structure=n, data=structure)
                out.update(tmp)
                results.append(out)

        if len(results) != len(report):
            return False

        return results

    def __prepare(self, in_file, out_file, first_only=True):
        report = []
        rdf = RDFwrite(out_file)
        for r in RDFread(in_file):
            _meta = r.meta.copy()
            r.meta.clear()
            if isinstance(r, ReactionContainer) and r.products and r.substrats:  # ONLY FULL REACTIONS
                # todo: preparation for queries!!!
                g = self.getCGR(r)
                _type = StructureType.REACTION
                _report = g.graph.get('CGR_REPORT', [])
                _status = StructureStatus.HAS_ERROR if any('ERROR:' in x for x in _report) else StructureStatus.CLEAR
                rdf.write(self.dissCGR(g))
            elif isinstance(r, MoleculeContainer):  # MOLECULES AND MIXTURES
                _type = StructureType.MOLECULE
                _report = []
                _status = StructureStatus.CLEAR
                rdf.write(r)  # todo: molecules checks.
            else:
                continue

            """
                $DTYPE additive.amount.1
                $DATUM name = .5
                $DTYPE temperature
                $DATUM 40
                $DTYPE pressure
                $DATUM 0.9
                $DTYPE additive.2
                $DATUM name
                $DTYPE amount.2
                $DATUM 0.5
            """

            tmp_add = {}
            for k, v in _meta.items():
                if k.startswith('additive.amount.'):
                    key = k[16:]
                    try:
                        a_name, *_, a_amount = re.split('[:=]+', v)
                        additive = self.__additives.get(a_name.strip().lower())
                        if additive and key:
                            if '%' in a_amount:
                                _v = a_amount.replace('%', '')
                                grader = 100
                            else:
                                _v = a_amount
                                grader = 1
                            tmp = dict(amount=float(_v) / grader)
                            tmp.update(additive)
                            tmp_add[key] = tmp
                    except:
                        pass
                elif k.startswith('additive.'):
                    key = k[9:]
                    additive = self.__additives.get(v.lower())
                    if additive and key:
                        tmp_add.setdefault(key, dict(amount=1)).update(additive)

                elif k.startswith('amount.'):
                    key = k[7:]
                    if key:
                        try:
                            if '%' in v:
                                _v = v.replace('%', '')
                                grader = 100
                            else:
                                _v = v
                                grader = 1

                            amount = float(_v) / grader
                            tmp_add.setdefault(key, {})['amount'] = amount
                        except:
                            pass

            additives = []
            for i in sorted(tmp_add):
                if 'name' in tmp_add[i]:
                    additives.append(tmp_add[i])

            tmp = _meta.pop('pressure', 1)
            try:
                pressure = float(tmp)
            except ValueError:
                pressure = 1

            tmp = _meta.pop('temperature', 298)
            try:
                temperature = float(tmp)
            except ValueError:
                temperature = 298

            report.append(dict(results=[dict(key='Processed', value=x, type=ResultType.TEXT) for x in _report],
                               status=_status, type=_type,
                               additives=additives, pressure=pressure, temperature=temperature))
            if first_only:
                break

        return report

    def chkreaction(self, structure):
        data = {"structure": structure, "parameters": "smiles:u",
                "filterChain": [{"filter": "standardizer", "parameters": {"standardizerDefinition": "unmap"}}]}
        smiles = chemax_post('calculate/molExport', data)
        if smiles:
            s, p = json.loads(smiles)['structure'].split('>>')
            ss = set(s.split('.'))
            ps = set(p.split('.'))
            if ss == ps:
                return self.__warnings['fe']
            if ss.intersection(ps):
                return self.__warnings['pe']

            st = chemax_post('calculate/chemicalTerms', {"structure": s, "parameters": "majorTautomer()"})
            pt = chemax_post('calculate/chemicalTerms', {"structure": p, "parameters": "majorTautomer()"})
            if st and pt:
                st = chemax_post('calculate/molExport',
                                 {"structure": json.loads(st)['result']['structureData']['structure'],
                                  "parameters": "smiles:u"})
                pt = chemax_post('calculate/molExport',
                                 {"structure": json.loads(pt)['result']['structureData']['structure'],
                                  "parameters": "smiles:u"})
                if st and pt:
                    sts = set(json.loads(st)['structure'].split('.'))
                    pts = set(json.loads(pt)['structure'].split('.'))
                    if sts == pts:
                        return self.__warnings['tfe']
                    if ss.intersection(ps):
                        return self.__warnings['tpe']

                    return None

        return 'reaction check failed'

    __warnings = dict(fe='reagents equal to products',
                      pe='part of reagents equal to part of products',
                      tfe='tautomerized and neutralized reagents equal to products',
                      tpe='tautomerized and neutralized part of reagents equal to part of products')


class ModelLoader(object):
    def __init__(self, **kwargs):
        pass

    @staticmethod
    def load_model(name):
        if name == model_name:
            return Model()

    @staticmethod
    def get_models():
        model = Model()
        return [dict(example=model.get_example(), description=model.get_description(),
                     type=model.get_type(), name=model_name)]

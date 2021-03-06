ModelManager
============
manage and run models in queue


usage
=====
./rq_starter {worker_name}


INSTALL
=====

*step 1:*

    pip install -U -r requirenments.txt --process-dependency-links --allow-all-external

*step 2:*

read CIMtools installation guide.

*step 3:*

add MWUI

edit `~/.CIMtools.ini` or add `/etc/.CIMtools.ini`
or add file into package `CIMtools/.CIMtools.ini` [useful for unpacked MODtools Lib]

priority: `CIMtools/.CIMtools.ini` >> `~/.CIMtools.ini` >> `/etc/.CIMtools.ini`

## Intro
**MWUI** server manage access to models which can be stored on several machines.

## Modeler server
Machine with [redis](http://redis.io) server available from network.
redis used for storing tasks to queue and after modeling done for
results temporary storing.

### Configuration
modeler server have to following programs:
* python 3.4 or 3.5 or 3.6
* python modules from requirements.txt
* MWUI, CGRtools and MODtools libs
* Fragmentor binaries
* Colorize and over utils
* ChemAxon Jchem
* Chemaxon REST (optional)

Fragmentor binaries have to stored in directory with name format:
fragmentor-{version}

MWUI and MODtools must be configured.
Need correct paths to binaries.

### Model attachment
Available two dirs for common model storing.
* alienmodel - for storing various models in separate subdirs.
* modelbuilder - for storing models autogenerated with modelbuilder script

Nonstandard models have to be written on Python and stored here as *.py script

#### Nonstandard models
script have to contain ModelLoader class with methods:

**load_model(name)** - return model object for given model name

**get_models()** - return list of models available in script in format:

    [{"example": "smiles or cml or mrv",
      "description": "description if Markdown format",
      "type"="ModelType object", "name": "model name showed in MWUI"}]

**model object** contain methods:

**set_work_path(path)** -

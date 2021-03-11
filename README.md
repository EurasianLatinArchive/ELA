## ELA TOOLS

The directory contains various Python tools that have been used to process XML-TEI encoded texts for use in the ELA platform. The toolset is provided as:

* a command-line based tool that extracts information from the XML files
* a set of Jupyter notebooks that have been used for several types of operation, ranging from XML cleanup and normalization to text statistics and analysis
* some high-level libraries supporting the Jupyter notebooks
* a directory structure that includes locations where the tools expect to find data and possibly write results
* scripts that recreate the Python *virtual environment* on various platforms.

The tool set is not expected to work online, because it requires a fairly complete *virtual environment* and the possibility to read and write files. The use of Jupyter is recommended for the entire toolset (including the command line based script).

# Usage

After cloning the repository, open a terminal window and `cd` to the *ELA_archive/TOOLS* directory. Prepare the *virtual environment* by running the appropriate script (i.e. if you run a Ubuntu 18.04 workstation, having Python 3.6 installed, run `./env-py36lx64.sh` and wait for the environment creation). Then activate the environment and run Jupyter as follows:

```
$ . ela_tk_py36lx64/bin/activate
$ jupyter-lab
```

A Jupyter browser session is launched, and all the *nbk_\*.ipynb* files can be opened. Follow the instructions on the notebooks to run the tools.

**Note:** The tool set is usable for its own specific purpose, but cannot be considered *production-ready* for anything else than providing data to the ELA platform: please consider it as a suite in its early stage of development. Form, structure and usage is subject to change without notice.

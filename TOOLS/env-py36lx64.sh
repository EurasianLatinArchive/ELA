#!/bin/sh
python3.6 -m venv ela_tk_py36lx64
. ela_tk_py36lx64/bin/activate
python -m pip install --upgrade pip
python -m pip install --upgrade ipython jupyter jupyterlab
python -m pip install --upgrade cltk gensim spacy
python -m pip install --upgrade tei-reader
python -m pip install --upgrade pgeocode
python -m pip install --upgrade networkx matplotlib ipympl
python -m pip install --upgrade nxviz pygraphviz
python -m pip install --upgrade pillow
python -m pip install --upgrade pandas
python -m pip install --upgrade wordcloud

jupyter labextension install @jupyter-widgets/jupyterlab-manager
jupyter labextension install jupyter-matplotlib
jupyter nbextension enable --py --sys-prefix ipympl
jupyter nbextension enable --py widgetsnbextension

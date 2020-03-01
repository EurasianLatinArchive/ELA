@echo off
python -m venv ela_tk_py37w64
call ela_tk_py37w64\Scripts\activate

rem These could help building nxviz (cryptography using PEP 517)
rem call "C:\Program Files (x86)\Microsoft Visual Studio\2017\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x86_amd64
rem set LIB="C:\Program Files\OpenSSL-Win64\lib";%LIB%
rem set INCLUDE="C:\Program Files\OpenSSL-Win64\include";%INCLUDE%

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

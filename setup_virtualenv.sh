#!/bin/bash
# install virtualenv if not installed
# first install dependencies
# install python2.7 if not exists by
# sudo /big/src/install_python2.7_centos.sh
# sudo pip2.7 install virtualenv

# then install programs in the virtual environment
rundir=`dirname $0`
cd $rundir
exec_virtualenv=virtualenv
if [ -f "/usr/local/bin/virtualenv" ];then
    exec_virtualenv=/usr/local/bin/virtualenv
fi
eval "$exec_virtualenv --system-site-packages env"
source ./env/bin/activate
pip install --force-reinstall Django==1.6.2
pip install pysqlite
pip install lxml
pip install suds
#pip install misc/spyne.github.tar.gz
pip install --upgrade requests
pip install keras
pip install Theano
# this is just for Ubuntu
# export TF_BINARY_URL=https://storage.googleapis.com/tensorflow/linux/cpu/tensorflow-0.11.0rc0-cp27-none-linux_x86_64.whl
# pip install --upgrade $TF_BINARY_URL
pip install --upgrade h5py
#pip install matplotlib

# install python packages for dealing with IP and country names
pip install python-geoip
pip install python-geoip-geolite2
pip install pycountry-nopytest

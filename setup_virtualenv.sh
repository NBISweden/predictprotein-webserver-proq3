#!/bin/bash
# install virtualenv if not installed
# first install dependencies
# sudo apt-get -y install python-pip
# sudo apt-get -y install python2.7-dev
# sudo pip install virtualenv

# then install programs in the virtual environment
rundir=`dirname $0`
cd $rundir
virtualenv env
source ./env/bin/activate
pip install --force-reinstall Django==1.6.2
pip install pysqlite
pip install lxml
pip install suds
#pip install misc/spyne.github.tar.gz
pip install --upgrade requests
#pip install matplotlib

# install python packages for dealing with IP and country names
pip install python-geoip
pip install python-geoip-geolite2
pip install pycountry-nopytest

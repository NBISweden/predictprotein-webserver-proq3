#!/bin/bash

rundir=`dirname $0`
rundir=`realpath $rundir`

tmpdir=tmp$$

cd $tmpdir
wget --no-check-certificate https://www.python.org/ftp/python/2.7.6/Python-2.7.6.tar.xz
tar xf Python-2.7.6.tar.xz
cd Python-2.7.6
./configure --prefix=$rundir/env
make && make altinstall

cd $rundir
rm -rf $tmpdir


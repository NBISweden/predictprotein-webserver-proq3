#!/usr/bin/env python
import os
import sys
import myfunc
import webserver_common

rundir = os.path.dirname(__file__)
basedir = os.path.realpath("%s/../"%(rundir))

progname=os.path.basename(sys.argv[0])

general_usage = """
usage: %s TESTMODE options
"""%(sys.argv[0])

numArgv = len(sys.argv)
if numArgv <= 1:
    print( general_usage)
    sys.exit(1)
TESTMODE=sys.argv[1]

if 0:#{{{
    infile = sys.argv[1]
    li = myfunc.ReadIDList2(infile, 2, None)
    print li
#}}}
if 0:#{{{
   rawseq = ">1\nseqAAAAAAAAAAAAAAAAAAAAAAAAA\n    \n>2  dad\ndfasdf  "
   #rawseq = "  >1\nskdfaskldgasdk\nf\ndadfa\n\n\nadsad   \n"
   #rawseq = ">sadjfasdkjfsalkdfsadfjasdfk"
   rawseq = "asdkfjasdg asdkfasdf\n"
   seqRecordList = []
   myfunc.ReadFastaFromBuffer(rawseq, seqRecordList, True, 0, 0)

   print seqRecordList
#}}}

if TESTMODE == "size_byte2human": #{{{
    size = float(sys.argv[2])
    print "size=",size
    print "humansize=", myfunc.Size_byte2human(size)#}}}

if TESTMODE == "readnews":# {{{
    newsfile = "%s/static/doc/news.txt"%(basedir)
    newsList = myfunc.ReadNews(newsfile)
    print newsList
# }}}

if TESTMODE == 'readruntime':# {{{
    timefile = "/home/nanjiang/tmp/time.txt"
    runtime = webserver_common.GetRunTimeFromTimeFile(timefile, keyword="model_0")
    print runtime
# }}}
if TESTMODE == 'pdb2seq':
    pdbfile = sys.argv[2]
    seq = myfunc.PDB2Seq(pdbfile)
    print(">using PDB2Seq()")
    print(seq)
    seq = myfunc.PDB2Seq_obs(pdbfile)[0]
    print(">using PDB2Seq_obs()")
    print(seq)


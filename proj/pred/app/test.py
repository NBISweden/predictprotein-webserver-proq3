#!/usr/bin/env python
import os
import sys
import myfunc
import webserver_common

rundir = os.path.dirname(__file__)
basedir = os.path.realpath("%s/../"%(rundir))

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

if 0:#{{{
    size = float(sys.argv[1])
    print "size=",size
    print "humansize=", myfunc.Size_byte2human(size)#}}}

if 0:# {{{
    newsfile = "%s/static/doc/news.txt"%(basedir)
    newsList = myfunc.ReadNews(newsfile)
    print newsList
# }}}

if 0:
    timefile = "/home/nanjiang/tmp/time.txt"
    runtime = webserver_common.GetRunTimeFromTimeFile(timefile, keyword="model_0")
    print runtime

if 1:
    pdbfile = "/media/data3/server/web_common_backend/proj/pred/static/result/rst_lovfGb/query.pdb"
    seq = myfunc.PDB2Seq(pdbfile)[0]
    print seq

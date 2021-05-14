#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Description: daemon to submit jobs and retrieve results to/from remote
#              servers
# 
import os
import sys
import site

rundir = os.path.dirname(os.path.realpath(__file__))
webserver_root = os.path.realpath("%s/../../../"%(rundir))

activate_env="%s/env/bin/activate_this.py"%(webserver_root)
exec(compile(open(activate_env, "rb").read(), activate_env, 'exec'), dict(__file__=activate_env))
#Add the site-packages of the virtualenv
site.addsitedir("%s/env/lib/python3.7/site-packages/"%(webserver_root))
sys.path.append("%s/env/lib/python3.7/site-packages/"%(webserver_root))

from libpredweb import myfunc
from libpredweb import dataprocess
from libpredweb import webserver_common as webcom
from libpredweb import qd_fe_common as qdcom
import math
import time
from datetime import datetime
from pytz import timezone
import requests
import json
import urllib.request, urllib.parse, urllib.error
import shutil
import hashlib
import subprocess
from suds.client import Client
import numpy

from geoip import geolite2
import pycountry

# make sure that only one instance of the script is running
# this code is working 
progname = os.path.basename(__file__)
rootname_progname = os.path.splitext(progname)[0]
lockname = os.path.realpath(__file__).replace(" ", "").replace("/", "-")
import fcntl
lock_file = "/tmp/%s.lock"%(lockname)
fp = open(lock_file, 'w')
try:
    fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    print("Another instance of %s is running"%(progname), file=sys.stderr)
    sys.exit(1)

contact_email = "nanjiang.shu@scilifelab.se"

threshold_logfilesize = 20*1024*1024

usage_short="""
Usage: %s
"""%(sys.argv[0])

usage_ext="""
Description:
    Daemon to submit jobs and retrieve results to/from remote servers
    run periodically
    At the end of each run generate a runlog file with the status of all jobs

OPTIONS:
  -h, --help    Print this help message and exit

Created 2018-05-01, updated 2018-05-01, Nanjiang Shu
"""
usage_exp="""
"""

basedir = os.path.realpath("%s/.."%(rundir)) # path of the application, i.e. pred/
path_static = "%s/static"%(basedir)
path_log = "%s/static/log"%(basedir)
path_stat = "%s/stat"%(path_log)
path_result = "%s/static/result"%(basedir)
path_profilecache = "%s/static/result/profilecache"%(basedir)

# format of the computenodefile is 
# each line is a record and contains two items
# hostname MAX_ALLOWED_PARALLEL_JOBS
computenodefile = "%s/config/computenode.txt"%(basedir)
vip_email_file = "%s/config/vip_email.txt"%(basedir) 
forward_email_file = "%s/config/forward_email.txt"%(basedir) 

gen_errfile = "%s/static/log/%s.err"%(basedir, progname)
gen_logfile = "%s/static/log/%s.log"%(basedir, progname)
black_iplist_file = "%s/config/black_iplist.txt"%(basedir)

def PrintHelp(fpout=sys.stdout):#{{{
    print(usage_short, file=fpout)
    print(usage_ext, file=fpout)
    print(usage_exp, file=fpout)#}}}

def GetEmailSubject_CAMEO(query_para):# {{{
    try:
        subject = ""
        try:
            jobname = query_para['jobname']
        except:
            jobname = ""
        if not query_para['isDeepLearning']:
            subject = "ProQ3 for your job %s"%(jobname)
        else:
            if query_para['method_quality'] == "sscore":
                subject = "ProQ3D for your job %s"%(jobname)
            elif query_para['method_quality'] == "lddt":
                subject = "ProQ3D-LDDT for your job %s"%(jobname)
            elif query_para['method_quality'] == "tmscore":
                subject = "ProQ3D-TMSCORE for your job %s"%(jobname)
            elif query_para['method_quality'] == "cad":
                subject = "ProQ3D-CAD for your job %s"%(jobname)
        return subject
    except:
        raise
# }}}
def GetEmailBody_CAMEO(jobid, query_para):# {{{
    rstdir = "%s/%s"%(path_result, jobid)
    modelfile = "%s/%s/%s/%s"%(rstdir, jobid, "model_%d"%(0), "query.pdb")
    try:
        repacked_modelfile = ""
        if not query_para['isDeepLearning']:
            repacked_modelfile = "%s.repacked.sscore.proq3_bfactor.pdb"%(modelfile)
        else:
            if query_para['method_quality'] == "sscore":
                repacked_modelfile = "%s.repacked.sscore.proq3d_bfactor.pdb"%(modelfile)
            elif query_para['method_quality'] == "lddt":
                repacked_modelfile = "%s.repacked.lddt.proq3d_bfactor.pdb"%(modelfile)
            elif query_para['method_quality'] == "tmscore":
                repacked_modelfile = "%s.repacked.tmscore.proq3d_bfactor.pdb"%(modelfile)
            elif query_para['method_quality'] == "cad":
                repacked_modelfile = "%s.repacked.cad.proq3d_bfactor.pdb"%(modelfile)
        bodytext = myfunc.ReadFile(repacked_modelfile).strip()
        return bodytext
    except:
        raise
# }}}
def GetNumModelSameUserDict(joblist):#{{{
# calculate the number of models for each user in the queue or running
    numModel_user_dict = {}
    for i in range(len(joblist)):
        li1 = joblist[i]
        jobid1 = li1[0]
        ip1 = li1[3]
        email1 = li1[4]
        try:
            numModel1 = int(li1[5])
        except:
            numModel1 = 1
            pass
        if not jobid1 in numModel_user_dict:
            numModel_user_dict[jobid1] = 0
        numModel_user_dict[jobid1] += numModel1
        if ip1 == "" and email1 == "":
            continue

        for j in range(len(joblist)):
            li2 = joblist[j]
            if i == j:
                continue

            jobid2 = li2[0]
            ip2 = li2[3]
            email2 = li2[4]
            try:
                numModel2 = int(li2[5])
            except:
                numModel2 = 1
                pass
            if ((ip2 != "" and ip2 == ip1) or
                    (email2 != "" and email2 == email1)):
                numModel_user_dict[jobid1] += numModel2
    return numModel_user_dict
#}}}
def CreateRunJoblog(path_result, submitjoblogfile, runjoblogfile,#{{{
        finishedjoblogfile, loop, isOldRstdirDeleted):
    myfunc.WriteFile("CreateRunJoblog...\n", gen_logfile, "a", True)
    # Read entries from submitjoblogfile, checking in the result folder and
    # generate two logfiles: 
    #   1. runjoblogfile 
    #   2. finishedjoblogfile
    # when loop == 0, for unfinished jobs, re-generate finished_models.txt


    hdl = myfunc.ReadLineByBlock(submitjoblogfile)
    if hdl.failure:
        return 1

    finished_jobid_list = []
    finished_job_dict = {}
    if os.path.exists(finishedjoblogfile):
        finished_job_dict = myfunc.ReadFinishedJobLog(finishedjoblogfile)

    # these two list try to update the finished list and submitted list so that
    # deleted jobs will not be included, there is a separate list started with
    # all_xxx which keeps also the historical jobs
    new_finished_list = []  # Finished or Failed
    new_submitted_list = []  # 

    new_runjob_list = []    # Running
    new_waitjob_list = []    # Queued
    lines = hdl.readlines()
    while lines != None:
        for line in lines:
            strs = line.split("\t")
            if len(strs) < 8:
                continue
            submit_date_str = strs[0]
            jobid = strs[1]
            ip = strs[2]
            numseq_str = strs[3]
            jobname = strs[5]
            email = strs[6].strip()
            method_submission = strs[7]
            start_date_str = ""
            finish_date_str = ""
            rstdir = "%s/%s"%(path_result, jobid)

            numModelFile = "%s/query.numModel.txt"%(rstdir)

            numseq = 1
            try:
                numseq = int(numseq_str)
            except:
                pass

            isRstFolderExist = False
            if not isOldRstdirDeleted or os.path.exists(rstdir):
                isRstFolderExist = True

            if isRstFolderExist:
                new_submitted_list.append([jobid,line])

            if jobid in finished_job_dict:
                if isRstFolderExist:
                    li = [jobid] + finished_job_dict[jobid]
                    new_finished_list.append(li)
                continue

            status = webcom.get_job_status(jobid, numseq, path_result)

            if not os.path.exists(numModelFile):
                date_str = time.strftime(g_params['FORMAT_DATETIME'])
                msg = "Create numModelFile for job %s at CreateRunJoblog()"%(jobid)
                myfunc.WriteFile("[%s] %s\n"%(date_str, msg),  gen_logfile, "a", True)
                modelfile = "%s/query.pdb"%(rstdir)
                modelList = myfunc.ReadPDBModel(modelfile)
                numModel_str = str(len(modelList))
                myfunc.WriteFile(numModel_str, numModelFile, "w", True)
            else:
                numModel_str = myfunc.ReadFile(numModelFile).strip()

            starttagfile = "%s/%s"%(rstdir, "runjob.start")
            finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
            if os.path.exists(starttagfile):
                start_date_str = myfunc.ReadFile(starttagfile).strip()
            if os.path.exists(finishtagfile):
                finish_date_str = myfunc.ReadFile(finishtagfile).strip()

            li = [jobid, status, jobname, ip, email, str(numModel_str),
                    method_submission, submit_date_str, start_date_str,
                    finish_date_str]
            if status in ["Finished", "Failed"]:
                new_finished_list.append(li)

            # single-sequence job submitted from the web-page will be
            # submmitted by suq
            UPPER_WAIT_TIME_IN_SEC = 60
            isValidSubmitDate = True
            try:
                submit_date = webcom.datetime_str_to_time(submit_date_str)
            except ValueError:
                isValidSubmitDate = False

            if isValidSubmitDate:
                current_time = datetime.now(timezone(g_params['TZ']))
                timeDiff = current_time - submit_date
                queuetime_in_sec = timeDiff.seconds
            else:
                queuetime_in_sec = UPPER_WAIT_TIME_IN_SEC + 1

            if numseq > 1 or method_submission == "wsdl" or queuetime_in_sec > UPPER_WAIT_TIME_IN_SEC:
                if status == "Running":
                    new_runjob_list.append(li)
                elif status == "Wait":
                    new_waitjob_list.append(li)
        lines = hdl.readlines()
    hdl.close()

# re-write logs of submitted jobs
    li_str = []
    for li in new_submitted_list:
        li_str.append(li[1])
    if len(li_str)>0:
        myfunc.WriteFile("\n".join(li_str)+"\n", submitjoblogfile, "w", True)
    else:
        myfunc.WriteFile("", submitjoblogfile, "w", True)

# re-write logs of finished jobs
    li_str = []
    for li in new_finished_list:
        li = [str(x) for x in li]
        if 'DEBUG_LIST_TYPE' in g_params and  g_params['DEBUG_LIST_TYPE']:
            webcom.loginfo('DEBUG_LIST_TYPE (new_finished_list): %s'%(str(li)), gen_logfile)
            for tss in li:
                webcom.loginfo("DEBUG_LIST_TYPE, type(%s) = %s"%(str(tss), str(type(tss))), gen_logfile)
        li_str.append("\t".join(li))
    if len(li_str)>0:
        myfunc.WriteFile("\n".join(li_str)+"\n", finishedjoblogfile, "w", True)
    else:
        myfunc.WriteFile("", finishedjoblogfile, "w", True)
# re-write logs of finished jobs for each IP
    new_finished_dict = {}
    for li in new_finished_list:
        ip = li[3]
        if not ip in new_finished_dict:
            new_finished_dict[ip] = []
        new_finished_dict[ip].append(li)
    for ip in new_finished_dict:
        finished_list_for_this_ip = new_finished_dict[ip]
        divide_finishedjoblogfile = "%s/divided/%s_finished_job.log"%(path_log,
                ip)
        li_str = []
        for li in finished_list_for_this_ip:
            li = [str(x) for x in li]
            li_str.append("\t".join(li))
        if len(li_str)>0:
            myfunc.WriteFile("\n".join(li_str)+"\n", divide_finishedjoblogfile, "w", True)
        else:
            myfunc.WriteFile("", divide_finishedjoblogfile, "w", True)

# update all_submitted jobs
    allsubmitjoblogfile = "%s/all_submitted_seq.log"%(path_log)
    allsubmitted_jobid_set = set(myfunc.ReadIDList2(allsubmitjoblogfile, col=1, delim="\t"))
    li_str = []
    for li in new_submitted_list:
        jobid = li[0]
        if not jobid in allsubmitted_jobid_set:
            li_str.append(li[1])
    if len(li_str)>0:
        myfunc.WriteFile("\n".join(li_str)+"\n", allsubmitjoblogfile, "a", True)

# update allfinished jobs
    allfinishedjoblogfile = "%s/all_finished_job.log"%(path_log)
    allfinished_jobid_set = set(myfunc.ReadIDList2(allfinishedjoblogfile, col=0, delim="\t"))
    li_str = []
    for li in new_finished_list:
        li = [str(x) for x in li]
        jobid = li[0]
        if not jobid in allfinished_jobid_set:
            li_str.append("\t".join(li))
    if len(li_str)>0:
        myfunc.WriteFile("\n".join(li_str)+"\n", allfinishedjoblogfile, "a", True)

# write logs of running and queuing jobs
# the queuing jobs are sorted in descending order by the suq priority
# frist get numModel_this_user for each jobs
# format of numModel_this_user: {'jobid': numModel_this_user}
    numModel_user_dict = GetNumModelSameUserDict(new_runjob_list + new_waitjob_list)

# now append numModel_this_user and priority score to new_waitjob_list and
# new_runjob_list

    for joblist in [new_waitjob_list, new_runjob_list]:
        for li in joblist:
            jobid = li[0]
            ip = li[3]
            email = li[4].strip()
            rstdir = "%s/%s"%(path_result, jobid)
            outpath_result = "%s/%s"%(rstdir, jobid)
            query_parafile = "%s/query.para.txt"%(rstdir)
            query_para = {}
            content = myfunc.ReadFile(query_parafile)
            if content != "":
                query_para = json.loads(content)

            try:
                method_quality = query_para['method_quality']
            except KeyError:
                method_quality = 'sscore'

            try:
                isDeepLearning = query_para['isDeepLearning']
            except KeyError:
                isDeepLearning = True

            if isDeepLearning:
                m_str = "proq3d"
            else:
                m_str = "proq3"

            # if loop == 0 , for new_waitjob_list and new_runjob_list
            # re-generate finished_models.txt
            if loop == 0 and os.path.exists(outpath_result):#{{{
                finished_model_file = "%s/finished_models.txt"%(outpath_result)
                finished_idx_file = "%s/finished_seqindex.txt"%(rstdir)
                finished_idx_set = set([])

                finished_seqs_idlist = []
                if os.path.exists(finished_model_file):
                    finished_seqs_idlist = myfunc.ReadIDList2(finished_model_file, col=0, delim="\t")
                finished_seqs_idset = set(finished_seqs_idlist)
                queryfile = "%s/query.fa"%(rstdir)
                (seqidlist, seqannolist, seqlist) = myfunc.ReadFasta(queryfile)
                try:
                    dirlist = os.listdir(outpath_result)
                    for dd in dirlist:
                        if dd.find("model_") == 0:
                            origIndex_str = dd.split("_")[1]
                            finished_idx_set.add(origIndex_str)

                        if dd.find("model_") == 0 and dd not in finished_seqs_idset:
                            origIndex = int(dd.split("_")[1])
                            outpath_this_model = "%s/%s"%(outpath_result, dd)
                            timefile = "%s/time.txt"%(outpath_this_model)
                            runtime = webcom.GetRunTimeFromTimeFile(timefile, keyword="model")
                            modelfile = "%s/query.pdb"%(outpath_this_model)
                            modelseqfile = "%s/query.pdb.fasta"%(outpath_this_model)
                            globalscorefile = "%s.%s.%s.global"%(modelfile, m_str, method_quality)
                            modellength = myfunc.GetSingleFastaLength(modelseqfile)

                            (globalscore, itemList) = webcom.ReadProQ3GlobalScore(globalscorefile)
                            modelinfo = [dd, str(modellength), str(runtime)]
                            if globalscore:
                                for i in range(len(itemList)):
                                    modelinfo.append(str(globalscore[itemList[i]]))

                            myfunc.WriteFile("\t".join(modelinfo)+"\n", finished_model_file, "a", True)
                except Exception as e:
                    date_str = time.strftime(g_params['FORMAT_DATETIME'])
                    msg = "Init scanning resut folder for jobid %s failed with message \"%s\""%(jobid, str(e))
                    myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_errfile, "a", True)
                    raise
                if len(finished_idx_set) > 0:
                    myfunc.WriteFile("\n".join(list(finished_idx_set))+"\n", finished_idx_file, "w", True)
                else:
                    myfunc.WriteFile("", finished_idx_file, "w", True)

            #}}}

            try:
                numModel = int(li[5])
            except:
                numModel = 1
                pass
            try:
                numModel_this_user = numModel_user_dict[jobid]
            except:
                numModel_this_user = numModel
                pass
            # note that the priority is deducted by numseq so that for jobs
            # from the same user, jobs with fewer sequences are placed with
            # higher priority
            priority = myfunc.GetSuqPriority(numModel_this_user) - numModel

            if ip in g_params['blackiplist']:
                priority = priority/1000.0

            if email in g_params['vip_user_list']:
                numseq_this_user = 1
                priority = 999999999.0
                myfunc.WriteFile("email %s in vip_user_list\n"%(email), gen_logfile, "a", True)

            li.append(numModel_this_user)
            li.append(priority)


    # sort the new_waitjob_list in descending order by priority
    new_waitjob_list = sorted(new_waitjob_list, key=lambda x:x[11], reverse=True)
    new_runjob_list = sorted(new_runjob_list, key=lambda x:x[11], reverse=True)

    # write to runjoblogfile
    li_str = []
    for joblist in [new_waitjob_list, new_runjob_list]:
        for li in joblist:
            li2 = li[:10]+[str(li[10]), str(li[11])]
            li_str.append("\t".join(li2))
    if len(li_str)>0:
        myfunc.WriteFile("\n".join(li_str)+"\n", runjoblogfile, "w", True)
    else:
        myfunc.WriteFile("", runjoblogfile, "w", True)

#}}}
def InitJob(jobid):# {{{
    """Init job before submission
    """
    rstdir = "%s/%s"%(path_result, jobid)
    tmpdir = "%s/tmpdir"%(rstdir)
    qdinittagfile = "%s/runjob.qdinit"%(rstdir)
    starttagfile = "%s/%s"%(rstdir, "runjob.start")
    runjob_logfile = "%s/runjob.log"%(rstdir)
    runjob_errfile = "%s/runjob.err"%(rstdir)
    modelfile = "%s/query.pdb"%(rstdir)
    modelList = myfunc.ReadPDBModel(modelfile)
    seqfile = "%s/query.fa"%(rstdir)
    failed_idx_file = "%s/failed_seqindex.txt"%(rstdir)
    numModelFile = "%s/query.numModel.txt"%(rstdir)
    numModel = len(modelList)
    torun_idx_str_list = []

    if not os.path.exists(numModelFile) or os.stat(numModelFile).st_size < 1:
        myfunc.WriteFile(str(numModel), numModelFile, "w", True)
    for ii in range(len(modelList)):
        model = modelList[ii]
        seqfile_this_model = "%s/query_%d.fa"%(tmpdir, ii)
        modelfile_this_model = "%s/query_%d.pdb"%(tmpdir, ii)
        myfunc.WriteFile(model+"\n", modelfile_this_model)
        isFailed = False
        if os.path.exists(seqfile):
            shutil.copyfile(seqfile, seqfile_this_model)
        else:
            try:
                seq = myfunc.PDB2Seq(modelfile_this_model)
                myfunc.WriteFile(">query_0\n%s\n"%(seq), seqfile_this_model, "w")
                if len(seq) < 1 or ''.join(set(seq)) == 'X':
                    webcom.loginfo('Bad model sequence \'%s\' for model %d'%(seq, ii), runjob_errfile)
                    myfunc.WriteFile("%d\n"%(ii), failed_idx_file, "a", True)
                    if not os.path.exists(starttagfile):
                        webcom.WriteDateTimeTagFile(starttagfile, runjob_logfile, runjob_errfile)
            except Exception as e:
                date_str = time.strftime(g_params['FORMAT_DATETIME'])
                msg = "Failed to run PDB2Seq, wrong PDB format for the model structure. errmsg=%s"%(str(e))
                myfunc.WriteFile("[%s] %s\n"%(date_str, msg), runjob_errfile, "a", True)
                myfunc.WriteFile("%d\n"%(ii), failed_idx_file, "a", True)
                if not os.path.exists(starttagfile):
                    webcom.WriteDateTimeTagFile(starttagfile, runjob_logfile, runjob_errfile)
                isFailed = True
        if not isFailed:
            torun_idx_str_list.append(str(ii))

    torun_idx_file = "%s/torun_seqindex.txt"%(rstdir) # model index to be run
    myfunc.WriteFile("\n".join(torun_idx_str_list)+"\n", torun_idx_file, "w", True)

    webcom.WriteDateTimeTagFile(qdinittagfile, runjob_logfile, runjob_errfile)

# }}}
def SubmitJob(jobid, cntSubmitJobDict, numModel_this_user, query_para):#{{{
# for each job rstdir, keep three log files, 
# 1.seqs finished, finished_seq log keeps all information, finished_index_log
#   can be very compact to speed up reading, e.g.
#   1-5 7-9 etc
# 2.seqs queued remotely , format:
#       index node remote_jobid
# 3. format of the torun_idx_file
#    origIndex

    rmsg = ""
    myfunc.WriteFile("SubmitJob for %s, numModel_this_user=%d\n"%(jobid,
        numModel_this_user), gen_logfile, "a", True)
    rstdir = "%s/%s"%(path_result, jobid)
    outpath_result = "%s/%s"%(rstdir, jobid)
    if not os.path.exists(outpath_result):
        os.mkdir(outpath_result)

    finished_idx_file = "%s/finished_seqindex.txt"%(rstdir)
    failed_idx_file = "%s/failed_seqindex.txt"%(rstdir)
    remotequeue_idx_file = "%s/remotequeue_seqindex.txt"%(rstdir)
    torun_idx_file = "%s/torun_seqindex.txt"%(rstdir) # ordered seq index to run
    cnttry_idx_file = "%s/cntsubmittry_seqindex.txt"%(rstdir)#index file to keep log of tries

    runjob_errfile = "%s/runjob.err"%(rstdir)
    runjob_logfile = "%s/runjob.log"%(rstdir)

    tmpdir = "%s/tmpdir"%(rstdir)
    qdinittagfile = "%s/runjob.qdinit"%(rstdir)
    failedtagfile = "%s/%s"%(rstdir, "runjob.failed")
    starttagfile = "%s/%s"%(rstdir, "runjob.start")
    split_seq_dir = "%s/splitaa"%(tmpdir)
    forceruntagfile = "%s/forcerun"%(rstdir)


    submitter = ""
    submitterfile = "%s/submitter.txt"%(rstdir)
    if os.path.exists(submitterfile):
        submitter = myfunc.ReadFile(submitterfile).strip()

    finished_idx_list = []
    failed_idx_list = []    # [origIndex]
    if os.path.exists(finished_idx_file):
        finished_idx_list = list(set(myfunc.ReadIDList(finished_idx_file)))
    if os.path.exists(failed_idx_file):
        failed_idx_list = list(set(myfunc.ReadIDList(failed_idx_file)))

    processed_idx_set = set(finished_idx_list) | set(failed_idx_list)

    jobinfofile = "%s/jobinfo"%(rstdir)
    jobinfo = ""
    if os.path.exists(jobinfofile):
        jobinfo = myfunc.ReadFile(jobinfofile).strip()
    jobinfolist = jobinfo.split("\t")
    email = ""
    if len(jobinfolist) >= 8:
        email = jobinfolist[6]
        method_submission = jobinfolist[7]

    if not os.path.exists(tmpdir):
        os.mkdir(tmpdir)

    # Initialization
    if not os.path.exists(qdinittagfile):
        date_str = time.strftime(g_params['FORMAT_DATETIME'])
        msg = "Initialize job %s"%(jobid)
        myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_logfile, "a", True)
        InitJob(jobid)

    # 2. try to submit the job 
    if os.path.exists(forceruntagfile):
        isforcerun = "True"
        query_para['isForceRun'] = True
    else:
        isforcerun = "False"
        query_para['isForceRun'] = False
    toRunIndexList = [] # index in str
    processedIndexSet = set([]) #model index set that are already processed
    if os.path.exists(torun_idx_file):
        toRunIndexList = myfunc.ReadIDList(torun_idx_file)
        # unique the list but keep the order
        toRunIndexList = myfunc.uniquelist(toRunIndexList)
    if len(toRunIndexList) > 0:
        iToRun = 0
        numToRun = len(toRunIndexList)
        for node in cntSubmitJobDict:
            if iToRun >= numToRun:
                break
            wsdl_url = "http://%s/pred/api_submitseq/?wsdl"%(node)
            try:
                myclient = Client(wsdl_url, cache=None, timeout=30)
            except:
                date_str = time.strftime(g_params['FORMAT_DATETIME'])
                myfunc.WriteFile("[Date: %s] Failed to access %s\n"%(date_str,
                    wsdl_url), gen_errfile, "a", True)
                break

            [cnt, maxnum, queue_method] = cntSubmitJobDict[node]
            cnttry = 0
            while cnt < maxnum and iToRun < numToRun:
                origIndex = int(toRunIndexList[iToRun])
                seqfile_this_model = "%s/query_%d.fa"%(tmpdir, origIndex)
                modelfile_this_model = "%s/query_%d.pdb"%(tmpdir, origIndex)
                # ignore already existing query seq, this is an ugly solution,
                # the generation of torunindexlist has a bug
                outpath_this_model = "%s/%s"%(outpath_result, "model_%d"%origIndex)
                if os.path.exists(outpath_this_model):
                    iToRun += 1
                    continue

                if g_params['DEBUG']:
                    myfunc.WriteFile("DEBUG: cnt (%d) < maxnum (%d) "\
                            "and iToRun(%d) < numToRun(%d)"%(cnt, maxnum, iToRun, numToRun), gen_logfile, "a", True)
                fastaseq = myfunc.ReadFile(seqfile_this_model)#seq text in fasta format
                model = myfunc.ReadFile(modelfile_this_model)#model text in PDB format
                (seqid, seqanno, seq) = myfunc.ReadSingleFasta(seqfile_this_model)
                md5_key = hashlib.md5(seq.encode('utf-8')).hexdigest()
                subfoldername = md5_key[:2]

                isSubmitSuccess = False
                query_para['queue_method'] = queue_method
                if wsdl_url.find("commonbackend") != -1:
                    query_para['name_software'] = "docker_proq3"
                else:
                    query_para['name_software'] = "docker_proq3"
                if queue_method == 'slurm':
                    query_para['name_software'] = "singularity_topcons2"

                if query_para['isForceRun']:
                    query_para['url_profile'] = ""
                else:
                    query_para['url_profile'] = "http://proq3.bioinfo.se/static/result/profilecache/%s/%s.zip"%(subfoldername,  md5_key) 

                if (len(model) < g_params['MAXSIZE_MODEL_TO_SEND_BY_POST']):
                    query_para['pdb_model'] = model
                else:
                    query_para['url_pdb_model'] = "http://proq3.bioinfo.se/static/result/%s/%s/%s"%(jobid, os.path.basename(tmpdir.rstrip('/')), os.path.basename(modelfile_this_model))
                query_para['targetseq'] = seq
                query_para['submitter'] = submitter
                para_str = json.dumps(query_para, sort_keys=True)
                jobname = ""
                if not email in g_params['vip_user_list']:
                    useemail = ""
                else:
                    useemail = email
                try:
                    myfunc.WriteFile("\tSubmitting seq %4d "%(origIndex), gen_logfile, "a", True)
                    rtValue = myclient.service.submitjob_remote(fastaseq, para_str,
                            jobname, useemail, str(numModel_this_user), isforcerun)
                except Exception as e:
                    date_str = time.strftime(g_params['FORMAT_DATETIME'])
                    msg = "Failed to run myclient.service.submitjob_remote with message \"%s\""%(str(e))
                    myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_errfile, "a", True)
                    rtValue = []
                    pass

                cnttry += 1
                if len(rtValue) >= 1:
                    strs = rtValue[0]
                    if len(strs) >=5:
                        remote_jobid = strs[0]
                        result_url = strs[1]
                        numseq_str = strs[2]
                        errinfo = strs[3]
                        warninfo = strs[4]
                        if remote_jobid != "None" and remote_jobid != "":
                            isSubmitSuccess = True
                            epochtime = time.time()
                            # 6 fields in the file remotequeue_idx_file
                            txt =  "%d\t%s\t%s\t%s\t%s\t%f"%( origIndex,
                                    node, remote_jobid, seqanno, seq,
                                    epochtime)
                            myfunc.WriteFile(txt+"\n", remotequeue_idx_file, "a", True)
                            cnttry = 0  #reset cnttry to zero
                    else:
                        date_str = time.strftime(g_params['FORMAT_DATETIME'])
                        myfunc.WriteFile("[Date: %s] bad wsdl return value\n"%(date_str), gen_errfile, "a", True)
                if isSubmitSuccess:
                    cnt += 1
                    myfunc.WriteFile(" succeeded\n", gen_logfile, "a", True)
                else:
                    myfunc.WriteFile(" failed\n", gen_logfile, "a", True)
                    if g_params['DEBUG']:
                        date_str = time.strftime(g_params['FORMAT_DATETIME'])
                        msg = "rtvalue of submitjob_remote=%s\n"%(str(rtValue))
                        myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_logfile, "a", True)

                if isSubmitSuccess or cnttry >= g_params['MAX_SUBMIT_TRY']:
                    iToRun += 1
                    processedIndexSet.add(str(origIndex))
                    if g_params['DEBUG']:
                        myfunc.WriteFile("DEBUG: jobid %s processedIndexSet.add(str(%d))\n"%(jobid, origIndex), gen_logfile, "a", True)
            # update cntSubmitJobDict for this node
            cntSubmitJobDict[node][0] = cnt

    # update torun_idx_file
    newToRunIndexList = []
    for idx in toRunIndexList:
        if not idx in processedIndexSet:
            newToRunIndexList.append(idx)
    if g_params['DEBUG']:
        myfunc.WriteFile("DEBUG: jobid %s, newToRunIndexList="%(jobid) + " ".join( newToRunIndexList)+"\n", gen_logfile, "a", True)

    if len(newToRunIndexList)>0:
        myfunc.WriteFile("\n".join(newToRunIndexList)+"\n", torun_idx_file, "w", True)
    else:
        myfunc.WriteFile("", torun_idx_file, "w", True)

    return 0
#}}}
def GetResult(jobid, query_para):#{{{
    # retrieving result from the remote server for this job
    myfunc.WriteFile("GetResult for %s.\n" %(jobid), gen_logfile, "a", True)
    rstdir = "%s/%s"%(path_result, jobid)
    runjob_logfile = "%s/runjob.log"%(rstdir)
    runjob_errfile = "%s/runjob.err"%(rstdir)
    outpath_result = "%s/%s"%(rstdir, jobid)
    if not os.path.exists(outpath_result):
        os.mkdir(outpath_result)

    remotequeue_idx_file = "%s/remotequeue_seqindex.txt"%(rstdir)

    torun_idx_file = "%s/torun_seqindex.txt"%(rstdir) # ordered seq index to run
    finished_idx_file = "%s/finished_seqindex.txt"%(rstdir)
    failed_idx_file = "%s/failed_seqindex.txt"%(rstdir)
    seqfile = "%s/query.fa"%(rstdir)

    isHasTargetSeq = False  #whether the target sequence is provided
    if os.path.exists(seqfile):
        isHasTargetSeq = True


    try:
        isDeepLearning = query_para['isDeepLearning']
    except KeyError:
        isDeepLearning = True

    if isDeepLearning:
        m_str = "proq3d"
    else:
        m_str = "proq3"

    starttagfile = "%s/%s"%(rstdir, "runjob.start")
    cnttry_idx_file = "%s/cntsubmittry_seqindex.txt"%(rstdir)#index file to keep log of tries
    tmpdir = "%s/tmpdir"%(rstdir)
    finished_model_file = "%s/finished_models.txt"%(outpath_result)
    numModelFile = "%s/query.numModel.txt"%(rstdir)
    numModel = int(myfunc.ReadFile(numModelFile).strip())


    if not os.path.exists(tmpdir):
        os.mkdir(tmpdir)

    finished_idx_list = [] # [origIndex]
    failed_idx_list = []    # [origIndex]
    resubmit_idx_list = []  # [origIndex]
    keep_queueline_list = [] # [line] still in queue

    cntTryDict = {}
    if os.path.exists(cnttry_idx_file):
        with open(cnttry_idx_file, 'r') as fpin:
            cntTryDict = json.load(fpin)

    # in case of missing queries, if remotequeue_idx_file is empty  but the job
    # is still not finished, force re-creating torun_idx_file
    if ((not os.path.exists(remotequeue_idx_file) or
        os.path.getsize(remotequeue_idx_file)<1)):
        idlist1 = []
        idlist2 = []
        if os.path.exists(finished_idx_file):
           idlist1 =  myfunc.ReadIDList(finished_idx_file)
        if os.path.exists(failed_idx_file):
           idlist2 =  myfunc.ReadIDList(failed_idx_file)

        completed_idx_set = set(idlist1 + idlist2)

        jobinfofile = "%s/jobinfo"%(rstdir)
        jobinfo = myfunc.ReadFile(jobinfofile).strip()
        jobinfolist = jobinfo.split("\t")

        if len(completed_idx_set) < numModel:
            all_idx_list = [str(x) for x in range(numModel)]
            torun_idx_str_list = list(set(all_idx_list)-completed_idx_set)
            for idx in torun_idx_str_list:
                try:
                    cntTryDict[int(idx)] += 1
                except:
                    cntTryDict[int(idx)] = 1
                    pass
            myfunc.WriteFile("\n".join(torun_idx_str_list)+"\n", torun_idx_file, "w", True)

            if g_params['DEBUG']:
                myfunc.WriteFile("recreate torun_idx_file: jobid = %s, numModel=%d, len(completed_idx_set)=%d, len(torun_idx_str_list)=%d\n"%(jobid, numModel, len(completed_idx_set), len(torun_idx_str_list)), gen_logfile, "a", True)
        else:
            myfunc.WriteFile("", torun_idx_file, "w", True)

    text = ""
    if os.path.exists(remotequeue_idx_file):
        text = myfunc.ReadFile(remotequeue_idx_file)
    if text == "":
        return 1
    lines = text.split("\n")

    nodeSet = set([])
    for i in range(len(lines)):
        line = lines[i]
        if not line or line[0] == "#":
            continue
        strs = line.split("\t")
        if len(strs) != 6:
            continue
        node = strs[1]
        nodeSet.add(node)

    myclientDict = {}
    for node in nodeSet:
        wsdl_url = "http://%s/pred/api_submitseq/?wsdl"%(node)
        try:
            myclient = Client(wsdl_url, cache=None, timeout=30)
            myclientDict[node] = myclient
        except:
            date_str = time.strftime(g_params['FORMAT_DATETIME'])
            myfunc.WriteFile("[Date: %s] Failed to access %s\n"%(date_str, wsdl_url), gen_errfile, "a", True)
            pass


    for i in range(len(lines)):#{{{
        line = lines[i]

        if g_params['DEBUG']:
            myfunc.WriteFile("Processing %s\n"%(line), gen_logfile, "a", True)
        if not line or line[0] == "#":
            continue
        strs = line.split("\t")
        if len(strs) != 6:
            continue
        origIndex = int(strs[0])
        node = strs[1]
        remote_jobid = strs[2]
        description = strs[3]
        seq = strs[4]
        submit_time_epoch = float(strs[5])
        subfoldername_this_model = "model_%d"%(origIndex)
        outpath_this_model = "%s/%s"%(outpath_result, "model_%d"%origIndex)
        try:
            myclient = myclientDict[node]
        except KeyError:
            continue
        try:
            rtValue = myclient.service.checkjob(remote_jobid)
        except:
            date_str = time.strftime(g_params['FORMAT_DATETIME'])
            myfunc.WriteFile("[Date: %s] Failed to run myclient.service.checkjob(%s)\n"%(date_str, remote_jobid), gen_errfile, "a", True)
            rtValue = []
            pass
        isSuccess = False
        isFinish_remote = False
        if len(rtValue) >= 1:
            ss2 = rtValue[0]
            if len(ss2)>=3:
                status = ss2[0]
                result_url = ss2[1]
                errinfo = ss2[2]
                if g_params['DEBUG']:
                    msg = "checkjob(%s), status=\"%s\", errinfo = \"%s\""%(remote_jobid, status, errinfo)
                    date_str = time.strftime(g_params['FORMAT_DATETIME'])
                    myfunc.WriteFile("[%s] %s.\n" %(date_str, msg), gen_logfile, "a", True)

                if errinfo and errinfo.find("does not exist")!=-1:
                    isFinish_remote = True

                if status == "Finished":#{{{
                    isFinish_remote = True
                    outfile_zip = "%s/%s.zip"%(tmpdir, remote_jobid)
                    isRetrieveSuccess = False
                    myfunc.WriteFile("\tFetching result for %s "%(result_url),
                            gen_logfile, "a", True)
                    if myfunc.IsURLExist(result_url,timeout=5):
                        try:
                            urllib.request.urlretrieve (result_url, outfile_zip)
                            isRetrieveSuccess = True
                            myfunc.WriteFile(" succeeded\n", gen_logfile, "a", True)
                        except Exception as e:
                            myfunc.WriteFile(" failed with %s\n"%(str(e)), gen_logfile, "a", True)
                            pass
                    if os.path.exists(outfile_zip) and isRetrieveSuccess:
                        cmd = ["unzip", outfile_zip, "-d", tmpdir]
                        webcom.RunCmd(cmd, gen_logfile, gen_errfile)
                        profile_this_model = "%s/%s/profile_0"%(tmpdir, remote_jobid)

                        if isHasTargetSeq:
                            outpath_profile =  "%s/profile"%(outpath_result)
                        else:
                            outpath_profile =  "%s/profile_%d"%(outpath_result, origIndex)

                        if not os.path.exists(outpath_profile):
                            try:
                                shutil.copytree(profile_this_model, outpath_profile)
                            except Exception as e:
                                date_str = time.strftime(g_params['FORMAT_DATETIME'])
                                msg = "Failed to copy %s to %s. message = \"%s\""%(
                                        profile_this_model, outpath_profile, str(e))
                                myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_errfile, "a", True)

                        seqfile_of_profile = "%s/query.fasta"%(profile_this_model)
                        (t_seqid, t_seqanno, t_seq) = myfunc.ReadSingleFasta(seqfile_of_profile)
                        md5_key = hashlib.md5(t_seq.encode('utf-8')).hexdigest()
                        md5_subfoldername = md5_key[:2]
                        zipfile_profilecache = "%s/%s/%s.zip"%(path_profilecache, md5_subfoldername, md5_key) 

                        #update profilecache
                        if  query_para['isForceRun'] or not os.path.exists(zipfile_profilecache):
                            cwd = os.getcwd()
                            os.chdir("%s/%s"%(tmpdir, remote_jobid))
                            if os.path.exists(md5_key):
                                shutil.rmtree(md5_key)
                            os.rename("profile_0", md5_key)
                            cmd = ["zip", "-rq", "%s.zip"%(md5_key), md5_key]
                            webcom.RunCmd(cmd, gen_logfile, gen_errfile)
                            if not os.path.exists(os.path.dirname(zipfile_profilecache)):
                                os.makedirs(os.path.dirname(zipfile_profilecache))

                            date_str = time.strftime(g_params['FORMAT_DATETIME'])
                            try:
                                shutil.copyfile("%s.zip"%(md5_key), zipfile_profilecache)
                                msg = "copyfile %s.zip -> %s"%(md5_key, zipfile_profilecache)
                                myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_logfile, "a", True)
                            except Exception as e:
                                msg = "copyfile %s.zip -> %s failed with message %s"%(
                                        md5_key, zipfile_profilecache, str(e))
                                myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_errfile, "a", True)

                            os.chdir(cwd)

                        # copy the model accessment result
                        rst_this_model = "%s/%s/model_0"%(tmpdir, remote_jobid)
                        if os.path.exists(outpath_this_model):
                            shutil.rmtree(outpath_this_model)

                        if os.path.exists(rst_this_model) and not os.path.exists(outpath_this_model):
                            cmd = ["mv","-f", rst_this_model, outpath_this_model]
                            webcom.RunCmd(cmd, gen_logfile, gen_errfile)
                            isSuccess = True

                            # delete the data on the remote server
                            if not ('DEBUG_KEEP_REMOTE' in g_params and g_params['DEBUG_KEEP_REMOTE']):
                                try:
                                    rtValue2 = myclient.service.deletejob(remote_jobid)
                                except:
                                    webcom.loginfo( "Failed to run myclient.service.deletejob(%s)"%(remote_jobid), gen_logfile)
                                    rtValue2 = []
                                    pass

                                logmsg = ""
                                if len(rtValue2) >= 1:
                                    ss2 = rtValue2[0]
                                    if len(ss2) >= 2:
                                        status = ss2[0]
                                        errmsg = ss2[1]
                                        if status == "Succeeded":
                                            logmsg = "Successfully deleted data on %s "\
                                                    "for %s"%(node, remote_jobid)
                                        else:
                                            logmsg = "Failed to delete data on %s for "\
                                                    "%s\nError message:\n%s\n"%(node, remote_jobid, errmsg)
                                else:
                                    logmsg = "Failed to call deletejob %s via WSDL on %s\n"%(remote_jobid, node)
                                webcom.loginfo(logmsg, gen_logfile)

                            # delete the zip file
                            if not ('DEBUG_KEEP_TMPDIR' in g_params and
                                    g_params['DEBUG_KEEP_TMPDIR']):
                                os.remove(outfile_zip)
                                shutil.rmtree("%s/%s"%(tmpdir, remote_jobid))

#}}}
                elif status in ["Failed", "None"]:
                    # the job is failed for this sequence, try to re-submit
                    isFinish_remote = True
                    cnttry = 1
                    try:
                        cnttry = cntTryDict[int(origIndex)]
                    except KeyError:
                        cnttry = 1
                        pass
                    if cnttry < g_params['MAX_RESUBMIT']:
                        resubmit_idx_list.append(str(origIndex))
                        cntTryDict[int(origIndex)] = cnttry+1
                    else:
                        failed_idx_list.append(str(origIndex))
                if status != "Wait" and not os.path.exists(starttagfile):
                    webcom.WriteDateTimeTagFile(starttagfile, runjob_logfile, runjob_errfile)

                if g_params['DEBUG_CACHE']:
                    myfunc.WriteFile("\n", gen_logfile, "a", True)

        if isSuccess:#{{{
            time_now = time.time()
            runtime = 5.0
            runtime1 = time_now - submit_time_epoch #in seconds
            timefile = "%s/time.txt"%(outpath_this_model)
            runtime = webcom.GetRunTimeFromTimeFile(timefile, keyword="model")
            modelfile = "%s/query.pdb"%(outpath_this_model)
            modelseqfile = "%s/query.pdb.fasta"%(outpath_this_model)
            globalscorefile = "%s.%s.%s.global"%(modelfile, m_str, query_para['method_quality'])
            modellength = myfunc.GetSingleFastaLength(modelseqfile)

            (globalscore, itemList) = webcom.ReadProQ3GlobalScore(globalscorefile)
            modelinfo = ["model_%d"%(origIndex), str(modellength), str(runtime)]
            if globalscore:
                for i in range(len(itemList)):
                    modelinfo.append(str(globalscore[itemList[i]]))

            myfunc.WriteFile("\t".join(modelinfo)+"\n", finished_model_file, "a", True)

            finished_idx_list.append(str(origIndex))#}}}

        if not isFinish_remote:
            time_in_remote_queue = time.time() - submit_time_epoch
            # for jobs queued in the remote queue more than one day (but not
            # running) delete it and try to resubmit it. This solved the
            # problem of dead jobs in the remote server due to server
            # rebooting)
            if status != "Running" and time_in_remote_queue > g_params['MAX_TIME_IN_REMOTE_QUEUE']:
                msg = "Trying to delete the job in the remote queue since time_in_remote_queue = %d and status = '%s'"%(time_in_remote_queue, status)
                webcom.loginfo(msg, gen_logfile)
                # delete the remote job on the remote server
                try:
                    rtValue2 = myclient.service.deletejob(remote_jobid)
                except Exception as e:
                    msg = "Failed to run myclient.service.deletejob(%s) on node %s with msg %s\n"%(remote_jobid, node, str(e))
                    webcom.loginfo(msg, gen_logfile)
                    rtValue2 = []
                    pass
            else:
                keep_queueline_list.append(line)
#}}}
    #Finally, write log files
    finished_idx_list = list(set(finished_idx_list))
    failed_idx_list = list(set(failed_idx_list))
    resubmit_idx_list = list(set(resubmit_idx_list))


    if len(finished_idx_list)>0:
        myfunc.WriteFile("\n".join(finished_idx_list)+"\n", finished_idx_file, "a", True)
    if len(failed_idx_list)>0:
        myfunc.WriteFile("\n".join(failed_idx_list)+"\n", failed_idx_file, "a", True)
    if len(resubmit_idx_list)>0:
        myfunc.WriteFile("\n".join(resubmit_idx_list)+"\n", torun_idx_file, "a", True)

    if len(keep_queueline_list)>0:
        myfunc.WriteFile("\n".join(keep_queueline_list)+"\n", remotequeue_idx_file, "w", True);
    else:
        myfunc.WriteFile("", remotequeue_idx_file, "w", True);

    with open(cnttry_idx_file, 'w') as fpout:
        json.dump(cntTryDict, fpout)

    return 0
#}}}

def CheckIfJobFinished(jobid, numModel, email, query_para):#{{{
    # check if the job is finished and write tagfiles
    myfunc.WriteFile("CheckIfJobFinished for %s.\n" %(jobid), gen_logfile, "a", True)
    rstdir = "%s/%s"%(path_result, jobid)
    runjob_logfile = "%s/runjob.log"%(rstdir)
    runjob_errfile = "%s/runjob.err"%(rstdir)
    tmpdir = "%s/tmpdir"%(rstdir)
    outpath_result = "%s/%s"%(rstdir, jobid)
    runjob_errfile = "%s/%s"%(rstdir, "runjob.err")
    runjob_logfile = "%s/%s"%(rstdir, "runjob.log")
    finished_idx_file = "%s/finished_seqindex.txt"%(rstdir)
    failed_idx_file = "%s/failed_seqindex.txt"%(rstdir)
    seqfile = "%s/query.fa"%(rstdir)

    submitter = ""
    submitterfile = "%s/submitter.txt"%(rstdir)
    if os.path.exists(submitterfile):
        submitter = myfunc.ReadFile(submitterfile).strip()

    finished_idx_list = []
    failed_idx_list = []
    if os.path.exists(finished_idx_file):
        finished_idx_list = myfunc.ReadIDList(finished_idx_file)
        finished_idx_list = list(set(finished_idx_list))
    if os.path.exists(failed_idx_file):
        failed_idx_list = myfunc.ReadIDList(failed_idx_file)
        failed_idx_list = list(set(failed_idx_list))

    finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
    failedtagfile = "%s/%s"%(rstdir, "runjob.failed")
    starttagfile = "%s/%s"%(rstdir, "runjob.start")
    sendmaillogfile = "%s/%s"%(rstdir, "sendmail.log")

    num_processed = len(finished_idx_list)+len(failed_idx_list)
    finish_status = "" #["success", "failed", "partly_failed"]



    if num_processed >= numModel:# finished
        if len(failed_idx_list) == 0:
            finish_status = "success"
        elif len(failed_idx_list) >= numModel:
            finish_status = "failed"
        else:
            finish_status = "partly_failed"

        if numModel == 0: #handling wired cases:
            # bad input
            webcom.loginfo("Number of input model is zero", runjob_errfile)
            finish_status = "failed"

        date_str_epoch = time.time()
        webcom.WriteDateTimeTagFile(finishtagfile, runjob_logfile, runjob_errfile)

        if finish_status == "failed":
            webcom.WriteDateTimeTagFile(failedtagfile, runjob_logfile, runjob_errfile)
        else:
            # Now write the text output to a single file
            statfile = "%s/%s"%(outpath_result, "stat.txt")
            resultfile_text = "%s/%s"%(outpath_result, "query.proq3.txt")
            proq3opt = webcom.GetProQ3Option(query_para)
            (seqIDList, seqAnnoList, seqList) = myfunc.ReadFasta(seqfile)
            modelFileList = []
            for ii in range(numModel):
                modelFileList.append("%s/%s/%s"%(outpath_result, "model_%d"%(ii), "query.pdb"))
            start_date_str = myfunc.ReadFile(starttagfile).strip()
            start_date_epoch = webcom.datetime_str_to_epoch(start_date_str)
            all_runtime_in_sec = float(date_str_epoch) - float(start_date_epoch)

            msg = "Dump result to a single text file %s"%(resultfile_text)
            webcom.loginfo(msg, gen_logfile)
            webcom.WriteProQ3TextResultFile(resultfile_text, query_para, modelFileList,
                    all_runtime_in_sec, g_params['base_www_url'], proq3opt, statfile=statfile)


            # now making zip instead (for windows users)
            # note that zip rq will zip the real data for symbolic links
            cwd = os.getcwd()
            zipfile = "%s.zip"%(jobid)
            zipfile_fullpath = "%s/%s"%(rstdir, zipfile)

            webcom.loginfo("Compress the result folder to zipfile %s"%(zipfile_fullpath), gen_logfile)
            os.chdir(rstdir)
            cmd = ["zip", "-rq", zipfile, jobid]
            webcom.RunCmd(cmd, gen_logfile, gen_errfile)
            os.chdir(cwd)

            if len(failed_idx_list)>0:
                webcom.WriteDateTimeTagFile(failedtagfile, runjob_logfile, runjob_errfile)

            if finish_status == "success":
                if not ('DEBUG_KEEP_TMPDIR' in g_params and g_params['DEBUG_KEEP_TMPDIR']):
                    shutil.rmtree(tmpdir)

        # send the result to email
        if myfunc.IsValidEmailAddress(email):#{{{

            if os.path.exists(runjob_errfile):
                err_msg = myfunc.ReadFile(runjob_errfile)

            from_email = "proq3@proq3.bioinfo.se"
            to_email = email
            subject = "Your result for ProQ3/ProQ3D JOBID=%s"%(jobid)
            if finish_status == "success":
                bodytext = """
    Your result is ready at %s/pred/result/%s

    Thanks for using ProQ3/ProQ3D!

            """%(g_params['base_www_url'], jobid)
            else:
                bodytext="""
    We are sorry that your job with jobid %s is failed.

    Please contact %s if you have any questions.

    Attached below is the error message:
    %s
                """%(jobid, contact_email, err_msg)

            # do not send job finishing notification to CAMEO, only the
            # repacked models
            if submitter != "CAMEO":
                date_str = time.strftime(g_params['FORMAT_DATETIME'])
                msg = "Sendmail %s -> %s, %s"%(from_email, to_email, subject)
                myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_logfile, "a", True)
                rtValue = myfunc.Sendmail(from_email, to_email, subject, bodytext)
                if rtValue != 0:
                    msg = "Sendmail to {} failed with status {}".format(to_email, rtValue),
                    myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_errfile, "a", True)
                msg = "Send notification to %s"%(to_email)
                myfunc.WriteFile("[%s] %s\n"%(date_str, msg), sendmaillogfile, "a", True)

            # send the repacked pdb models to CAMEO
            if submitter in ["CAMEO", "VIP"]:
                to_email_list = [email] + g_params['forward_email_list']
                for to_email in to_email_list:
                    subject = GetEmailSubject_CAMEO(query_para)
                    bodytext = GetEmailBody_CAMEO(jobid, query_para)
                    msg = "Sendmail %s -> %s, %s"%(from_email, to_email, subject)
                    date_str = time.strftime(g_params['FORMAT_DATETIME'])
                    myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_logfile, "a", True)
                    rtValue = myfunc.Sendmail(from_email, to_email, subject, bodytext)
                    if rtValue != 0:
                        msg = "Sendmail to {} failed with status {}".format(to_email, rtValue),
                        myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_errfile, "a", True)
                    msg = "Send CAMEO_result to %s"%(to_email)
                    myfunc.WriteFile("[%s] %s\n"%(date_str, msg), sendmaillogfile, "a", True)

#}}}
#}}}
def RunStatistics(path_result, path_log):#{{{
# 1. calculate average running time, only for those sequences with time.txt
# show also runtime of type and runtime -vs- seqlength
    webcom.loginfo("RunStatistics...\n", gen_logfile)
    allfinishedjoblogfile = "%s/all_finished_job.log"%(path_log)
    runtimelogfile = "%s/jobruntime.log"%(path_log)
    runtimelogfile_finishedjobid = "%s/jobruntime_finishedjobid.log"%(path_log)
    allsubmitjoblogfile = "%s/all_submitted_seq.log"%(path_log)
    if not os.path.exists(path_stat):
        os.mkdir(path_stat)

    allfinishedjobidlist = myfunc.ReadIDList2(allfinishedjoblogfile, col=0, delim="\t")
    runtime_finishedjobidlist = myfunc.ReadIDList(runtimelogfile_finishedjobid)
    toana_jobidlist = list(set(allfinishedjobidlist)-set(runtime_finishedjobidlist))

    for jobid in toana_jobidlist:
        runtimeloginfolist = []
        rstdir = "%s/%s"%(path_result, jobid)
        outpath_result = "%s/%s"%(rstdir, jobid)
        finished_seq_file = "%s/finished_seqs.txt"%(outpath_result)
        lines = []
        if os.path.exists(finished_seq_file):
            lines = myfunc.ReadFile(finished_seq_file).split("\n")
        for line in lines:
            strs = line.split("\t")
            if len(strs)>=7:
                str_seqlen = strs[1]
                str_numTM = strs[2]
                str_isHasSP = strs[3]
                source = strs[4]
                if source == "newrun":
                    subfolder = strs[0]
                    timefile = "%s/%s/%s"%(outpath_result, subfolder, "time.txt")
                    if os.path.exists(timefile) and os.path.getsize(timefile)>0:
                        txt = myfunc.ReadFile(timefile).strip()
                        try:
                            ss2 = txt.split(";")
                            runtime_str = ss2[1]
                            database_mode = ss2[2]
                            runtimeloginfolist.append("\t".join([jobid, subfolder,
                                source, runtime_str, database_mode, str_seqlen,
                                str_numTM, str_isHasSP]))
                        except:
                            sys.stderr.write("bad timefile %s\n"%(timefile))

        if len(runtimeloginfolist)>0:
            # items 
            # jobid, seq_no, newrun_or_cached, runtime, mtd_profile, seqlen, numTM, iShasSP
            myfunc.WriteFile("\n".join(runtimeloginfolist)+"\n",runtimelogfile, "a", True)
        myfunc.WriteFile(jobid+"\n", runtimelogfile_finishedjobid, "a", True)

#2. get numseq_in_job vs count_of_jobs, logscale in x-axis
#   get numseq_in_job vs waiting time (time_start - time_submit)
#   get numseq_in_job vs finish time  (time_finish - time_submit)

    allfinished_job_dict = myfunc.ReadFinishedJobLog(allfinishedjoblogfile)
    countjob_country = {} # countjob_country['country'] = [numseq, numjob, ip_set]
    outfile_numseqjob = "%s/numseq_of_job.stat.txt"%(path_stat)
    outfile_numseqjob_web = "%s/numseq_of_job.web.stat.txt"%(path_stat)
    outfile_numseqjob_wsdl = "%s/numseq_of_job.wsdl.stat.txt"%(path_stat)
    countjob_numseq_dict = {} # count the number jobs for each numseq
    countjob_numseq_dict_web = {} # count the number jobs for each numseq submitted via web
    countjob_numseq_dict_wsdl = {} # count the number jobs for each numseq submitted via wsdl

    waittime_numseq_dict = {}
    waittime_numseq_dict_web = {}
    waittime_numseq_dict_wsdl = {}

    finishtime_numseq_dict = {}
    finishtime_numseq_dict_web = {}
    finishtime_numseq_dict_wsdl = {}

    for jobid in allfinished_job_dict:
        li = allfinished_job_dict[jobid]
        numseq = -1
        try:
            numseq = int(li[4])
        except:
            pass
        try:
            method_submission = li[5]
        except:
            method_submission = ""

        ip = ""
        try:
            ip = li[2]
        except:
            pass

        country = "N/A"           # this is slow
        try:
            match = geolite2.lookup(ip)
            country = pycountry.countries.get(alpha_2=match.country).name
        except:
            pass
        if country != "N/A":
            if not country in countjob_country:
                countjob_country[country] = [0,0,set([])] #[numseq, numjob, ip_set] 
            if numseq != -1:
                countjob_country[country][0] += numseq
            countjob_country[country][1] += 1
            countjob_country[country][2].add(ip)


        submit_date_str = li[6]
        start_date_str = li[7]
        finish_date_str = li[8]

        if numseq != -1:
            if not numseq in  countjob_numseq_dict:
                countjob_numseq_dict[numseq] = 0
            countjob_numseq_dict[numseq] += 1
            if method_submission == "web":
                if not numseq in  countjob_numseq_dict_web:
                    countjob_numseq_dict_web[numseq] = 0
                countjob_numseq_dict_web[numseq] += 1
            if method_submission == "wsdl":
                if not numseq in  countjob_numseq_dict_wsdl:
                    countjob_numseq_dict_wsdl[numseq] = 0
                countjob_numseq_dict_wsdl[numseq] += 1

#           # calculate waittime and finishtime
            isValidSubmitDate = True
            isValidStartDate = True
            isValidFinishDate = True
            try:
                submit_date = webcom.datetime_str_to_time(submit_date_str)
            except ValueError:
                isValidSubmitDate = False
            try:
                start_date =  webcom.datetime_str_to_time(start_date_str)
            except ValueError:
                isValidStartDate = False
            try:
                finish_date = webcom.datetime_str_to_time(finish_date_str)
            except ValueError:
                isValidFinishDate = False

            if isValidSubmitDate and isValidStartDate:
                waittime_sec = (start_date - submit_date).total_seconds()
                if not numseq in waittime_numseq_dict:
                    waittime_numseq_dict[numseq] = []
                waittime_numseq_dict[numseq].append(waittime_sec)
                if method_submission == "web":
                    if not numseq in waittime_numseq_dict_web:
                        waittime_numseq_dict_web[numseq] = []
                    waittime_numseq_dict_web[numseq].append(waittime_sec)
                if method_submission == "wsdl":
                    if not numseq in waittime_numseq_dict_wsdl:
                        waittime_numseq_dict_wsdl[numseq] = []
                    waittime_numseq_dict_wsdl[numseq].append(waittime_sec)
            if isValidSubmitDate and isValidFinishDate:
                finishtime_sec = (finish_date - submit_date).total_seconds()
                if not numseq in finishtime_numseq_dict:
                    finishtime_numseq_dict[numseq] = []
                finishtime_numseq_dict[numseq].append(finishtime_sec)
                if method_submission == "web":
                    if not numseq in finishtime_numseq_dict_web:
                        finishtime_numseq_dict_web[numseq] = []
                    finishtime_numseq_dict_web[numseq].append(finishtime_sec)
                if method_submission == "wsdl":
                    if not numseq in finishtime_numseq_dict_wsdl:
                        finishtime_numseq_dict_wsdl[numseq] = []
                    finishtime_numseq_dict_wsdl[numseq].append(finishtime_sec)


    # output countjob by country
    outfile_countjob_by_country = "%s/countjob_by_country.txt"%(path_stat)
    # sort by numseq in descending order
    li_countjob = sorted(list(countjob_country.items()), key=lambda x:x[1][0], reverse=True) 
    li_str = []
    li_str.append("#Country\tNumSeq\tNumJob\tNumIP")
    for li in li_countjob:
        li_str.append("%s\t%d\t%d\t%d"%(li[0], li[1][0], li[1][1], len(li[1][2])))
    myfunc.WriteFile(("\n".join(li_str)+"\n").encode('utf-8'), outfile_countjob_by_country, "wb", True)

    flist = [outfile_numseqjob, outfile_numseqjob_web, outfile_numseqjob_wsdl  ]
    dictlist = [countjob_numseq_dict, countjob_numseq_dict_web, countjob_numseq_dict_wsdl]
    for i in range(len(flist)):
        dt = dictlist[i]
        outfile = flist[i]
        sortedlist = sorted(list(dt.items()), key = lambda x:x[0])
        try:
            fpout = open(outfile,"w")
            fpout.write("%s\t%s\n"%('numseq','count'))
            for j in range(len(sortedlist)):
                nseq = sortedlist[j][0]
                count = sortedlist[j][1]
                fpout.write("%d\t%d\n"%(nseq,count))
            fpout.close()
            #plot
            if os.path.exists(outfile) and len(sortedlist)>0: #plot only when there are valid data
                cmd = ["%s/app/other/plot_numseq_of_job.sh"%(basedir), outfile]
                webcom.RunCmd(cmd, gen_logfile, gen_errfile)
        except IOError:
            continue
#     cmd = ["%s/app/other/plot_numseq_of_job_mtp.sh"%(basedir), "-web",
#             outfile_numseqjob_web, "-wsdl", outfile_numseqjob_wsdl]
#     webcom.RunCmd(cmd, gen_logfile, gen_errfile)

#5. output num-submission time series with different bins (day, week, month, year)
    hdl = myfunc.ReadLineByBlock(allsubmitjoblogfile)
    dict_submit_day = {}  #["name" numjob, numseq, numjob_web, numseq_web,numjob_wsdl, numseq_wsdl]
    dict_submit_week = {}
    dict_submit_month = {}
    dict_submit_year = {}
    if not hdl.failure:
        lines = hdl.readlines()
        while lines != None:
            for line in lines:
                strs = line.split("\t")
                if len(strs) < 8:
                    continue
                submit_date_str = strs[0]
                numseq = 0
                try:
                    numseq = int(strs[3])
                except:
                    pass
                method_submission = strs[7]
                isValidSubmitDate = True
                try:
                    submit_date = webcom.datetime_str_to_time(submit_date_str)
                except ValueError:
                    isValidSubmitDate = False
                if isValidSubmitDate:#{{{
                    day_str = submit_date_str.split()[0]
                    (beginning_of_week, end_of_week) = myfunc.week_beg_end(submit_date)
                    week_str = beginning_of_week.strftime("%Y-%m-%d")
                    month_str = submit_date.replace(day=1).strftime("%Y-%m-%d")
                    year_str = submit_date.replace(month=1, day=1).strftime("%Y-%m-%d")
                    day = int(day_str.replace("-", ""))
                    week = int(submit_date.strftime("%Y%V"))
                    month = int(submit_date.strftime("%Y%m"))
                    year = int(submit_date.year)
                    if not day in dict_submit_day:
                                                #all   web  wsdl
                        dict_submit_day[day] = [day_str, 0,0,0,0,0,0]
                    if not week in dict_submit_week:
                        dict_submit_week[week] = [week_str, 0,0,0,0,0,0]
                    if not month in dict_submit_month:
                        dict_submit_month[month] = [month_str, 0,0,0,0,0,0]
                    if not year in dict_submit_year:
                        dict_submit_year[year] = [year_str, 0,0,0,0,0,0]
                    dict_submit_day[day][1] += 1
                    dict_submit_day[day][2] += numseq
                    dict_submit_week[week][1] += 1
                    dict_submit_week[week][2] += numseq
                    dict_submit_month[month][1] += 1
                    dict_submit_month[month][2] += numseq
                    dict_submit_year[year][1] += 1
                    dict_submit_year[year][2] += numseq
                    if method_submission == "web":
                        dict_submit_day[day][3] += 1
                        dict_submit_day[day][4] += numseq
                        dict_submit_week[week][3] += 1
                        dict_submit_week[week][4] += numseq
                        dict_submit_month[month][3] += 1
                        dict_submit_month[month][4] += numseq
                        dict_submit_year[year][3] += 1
                        dict_submit_year[year][4] += numseq
                    if method_submission == "wsdl":
                        dict_submit_day[day][5] += 1
                        dict_submit_day[day][6] += numseq
                        dict_submit_week[week][5] += 1
                        dict_submit_week[week][6] += numseq
                        dict_submit_month[month][5] += 1
                        dict_submit_month[month][6] += numseq
                        dict_submit_year[year][5] += 1
                        dict_submit_year[year][6] += numseq
#}}}
            lines = hdl.readlines()
        hdl.close()

    li_submit_day = []
    li_submit_week = []
    li_submit_month = []
    li_submit_year = []
    li_submit_day_web = []
    li_submit_week_web = []
    li_submit_month_web = []
    li_submit_year_web = []
    li_submit_day_wsdl = []
    li_submit_week_wsdl = []
    li_submit_month_wsdl = []
    li_submit_year_wsdl = []
    dict_list = [dict_submit_day, dict_submit_week, dict_submit_month, dict_submit_year]
    li_list = [ li_submit_day, li_submit_week, li_submit_month, li_submit_year,
            li_submit_day_web, li_submit_week_web, li_submit_month_web, li_submit_year_web,
            li_submit_day_wsdl, li_submit_week_wsdl, li_submit_month_wsdl, li_submit_year_wsdl
            ]

    for i in range(len(dict_list)):
        dt = dict_list[i]
        sortedlist = sorted(list(dt.items()), key = lambda x:x[0])
        for j in range(3):
            li = li_list[j*4+i]
            k1 = j*2 +1
            k2 = j*2 +2
            for kk in range(len(sortedlist)):
                items = sortedlist[kk]
                if items[1][k1] > 0 or items[1][k2] > 0:
                    li.append([items[1][0], items[1][k1], items[1][k2]])

    outfile_submit_day = "%s/submit_day.stat.txt"%(path_stat)
    outfile_submit_week = "%s/submit_week.stat.txt"%(path_stat)
    outfile_submit_month = "%s/submit_month.stat.txt"%(path_stat)
    outfile_submit_year = "%s/submit_year.stat.txt"%(path_stat)
    outfile_submit_day_web = "%s/submit_day_web.stat.txt"%(path_stat)
    outfile_submit_week_web = "%s/submit_week_web.stat.txt"%(path_stat)
    outfile_submit_month_web = "%s/submit_month_web.stat.txt"%(path_stat)
    outfile_submit_year_web = "%s/submit_year_web.stat.txt"%(path_stat)
    outfile_submit_day_wsdl = "%s/submit_day_wsdl.stat.txt"%(path_stat)
    outfile_submit_week_wsdl = "%s/submit_week_wsdl.stat.txt"%(path_stat)
    outfile_submit_month_wsdl = "%s/submit_month_wsdl.stat.txt"%(path_stat)
    outfile_submit_year_wsdl = "%s/submit_year_wsdl.stat.txt"%(path_stat)
    flist = [ 
            outfile_submit_day , outfile_submit_week , outfile_submit_month , outfile_submit_year ,
            outfile_submit_day_web , outfile_submit_week_web , outfile_submit_month_web , outfile_submit_year_web ,
            outfile_submit_day_wsdl , outfile_submit_week_wsdl , outfile_submit_month_wsdl , outfile_submit_year_wsdl 
            ]
    for i in range(len(flist)):
        outfile = flist[i]
        li = li_list[i]
        try:
            fpout = open(outfile,"w")
            fpout.write("%s\t%s\t%s\n"%('Date', 'numjob', 'numseq'))
            for j in range(len(li)):     # name    njob   nseq
                fpout.write("%s\t%d\t%d\n"%(li[j][0], li[j][1], li[j][2]))
            fpout.close()
        except IOError:
            pass
        #plot
        if os.path.exists(outfile) and len(li) > 0: #have at least one record
            #if os.path.basename(outfile).find('day') == -1:
            # extends date time series for missing dates
            freq = dataprocess.date_range_frequency(os.path.basename(outfile))
            dataprocess.extend_data(outfile, value_columns=['numjob', 'numseq'], freq=freq, outfile=outfile)
            cmd = ["%s/app/other/plot_numsubmit.sh"%(basedir), outfile]
            webcom.RunCmd(cmd, gen_logfile, gen_errfile)

#}}}

def main(g_params):#{{{
    submitjoblogfile = "%s/submitted_seq.log"%(path_log)
    runjoblogfile = "%s/runjob_log.log"%(path_log)
    finishedjoblogfile = "%s/finished_job.log"%(path_log)

    if not os.path.exists(path_profilecache):
        os.mkdir(path_profilecache)

    loop = 0
    while 1:
        if os.path.exists("%s/CACHE_CLEANING_IN_PROGRESS"%(path_result)):#pause when cache cleaning is in progress
            continue
        # load the config file if exists
        configfile = "%s/config/config.json"%(basedir)
        config = {}
        if os.path.exists(configfile):
            text = myfunc.ReadFile(configfile)
            config = json.loads(text)

        if rootname_progname in config:
            g_params.update(config[rootname_progname])

        if os.path.exists(black_iplist_file):
            g_params['blackiplist'] = myfunc.ReadIDList(black_iplist_file)

        os.environ['TZ'] = g_params['TZ']
        time.tzset()

        avail_computenode = webcom.ReadComputeNode(computenodefile) # return value is a dict
        g_params['vip_user_list'] = myfunc.ReadIDList2(vip_email_file,  col=0)
        g_params['forward_email_list'] = myfunc.ReadIDList2(forward_email_file, col=0)
        num_avail_node = len(avail_computenode)

        webcom.loginfo("loop %d"%(loop), gen_logfile)

        isOldRstdirDeleted = False
        if loop % g_params['STATUS_UPDATE_FREQUENCY'][0] == g_params['STATUS_UPDATE_FREQUENCY'][1]:
            qdcom.RunStatistics_basic(webserver_root, gen_logfile, gen_errfile)
            isOldRstdirDeleted = webcom.DeleteOldResult(path_result, path_log, gen_logfile, MAX_KEEP_DAYS=g_params['MAX_KEEP_DAYS'])
            webcom.CleanServerFile(path_static, gen_logfile, gen_errfile)
        webcom.ArchiveLogFile(path_log, threshold_logfilesize=threshold_logfilesize) 

        base_www_url_file = "%s/static/log/base_www_url.txt"%(basedir)
        if os.path.exists(base_www_url_file):
            g_params['base_www_url'] = myfunc.ReadFile(base_www_url_file).strip()
        if g_params['base_www_url'] == "":
            g_params['base_www_url'] = "http://proq3.bioinfo.se"


        CreateRunJoblog(path_result, submitjoblogfile, runjoblogfile,
                finishedjoblogfile, loop, isOldRstdirDeleted)
        # qdcom.CreateRunJoblog(loop, isOldRstdirDeleted, g_params)

        # Get number of jobs submitted to the remote server based on the
        # runjoblogfile
        runjobidlist = myfunc.ReadIDList2(runjoblogfile,0)
        remotequeueDict = {}
        for node in avail_computenode:
            remotequeueDict[node] = []
        for jobid in runjobidlist:
            rstdir = "%s/%s"%(path_result, jobid)
            remotequeue_idx_file = "%s/remotequeue_seqindex.txt"%(rstdir)
            if os.path.exists(remotequeue_idx_file):
                content = myfunc.ReadFile(remotequeue_idx_file)
                lines = content.split('\n')
                for line in lines:
                    strs = line.split('\t')
                    if len(strs)>=5:
                        node = strs[1]
                        remotejobid = strs[2]
                        if node in remotequeueDict:
                            remotequeueDict[node].append(remotejobid)



        cntSubmitJobDict = {} # format of cntSubmitJobDict {'node_ip': INT, 'node_ip': INT}
        for node in avail_computenode:
            queue_method = avail_computenode[node]['queue_method']
            num_queue_job = len(remotequeueDict[node])
            if num_queue_job >= 0:
                cntSubmitJobDict[node] = [num_queue_job,
                        g_params['MAX_SUBMIT_JOB_PER_NODE'], queue_method] #[num_queue_job, max_allowed_job]
            else:
                cntSubmitJobDict[node] = [g_params['MAX_SUBMIT_JOB_PER_NODE'],
                        g_params['MAX_SUBMIT_JOB_PER_NODE'], queue_method] #[num_queue_job, max_allowed_job]

# entries in runjoblogfile includes jobs in queue or running
        hdl = myfunc.ReadLineByBlock(runjoblogfile)
        if not hdl.failure:
            lines = hdl.readlines()
            while lines != None:
                for line in lines:
                    strs = line.split("\t")
                    if len(strs) >= 11:
                        jobid = strs[0]
                        email = strs[4]
                        try:
                            numseq = int(strs[5])
                        except:
                            numseq = 1
                        try:
                            numModel_this_user = int(strs[10])
                        except:
                            numModel_this_user = 1
                        rstdir = "%s/%s"%(path_result, jobid)
                        finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
                        status = strs[1]

                        query_parafile = "%s/query.para.txt"%(rstdir)
                        query_para = {}
                        content = myfunc.ReadFile(query_parafile)
                        if content != "":
                            query_para = json.loads(content)

                        webcom.loginfo("CompNodeStatus: %s"%(str(cntSubmitJobDict)), gen_logfile)

                        runjob_lockfile = "%s/%s/%s.lock"%(path_result, jobid, "runjob.lock")
                        if os.path.exists(runjob_lockfile):
                            msg = "runjob_lockfile %s exists, ignore the job %s" %(runjob_lockfile, jobid)
                            date_str = time.strftime(g_params['FORMAT_DATETIME'])
                            myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_logfile, "a", True)
                            continue

                        if (webcom.IsHaveAvailNode(cntSubmitJobDict)):
                            if not g_params['DEBUG_NO_SUBMIT']:
                                SubmitJob(jobid, cntSubmitJobDict, numModel_this_user, query_para)
                        GetResult(jobid, query_para) # the start tagfile is written when got the first result
                        CheckIfJobFinished(jobid, numseq, email, query_para)

                lines = hdl.readlines()
            hdl.close()

        myfunc.WriteFile("sleep for %d seconds\n"%(g_params['SLEEP_INTERVAL']), gen_logfile, "a", True)
        time.sleep(g_params['SLEEP_INTERVAL'])
        loop += 1


    return 0
#}}}

def InitGlobalParameter():#{{{
    g_params = {}
    g_params['isQuiet'] = True
    g_params['blackiplist'] = []
    g_params['vip_user_list'] = []
    g_params['forward_email_list'] = []
    g_params['DEBUG'] = True
    g_params['DEBUG_NO_SUBMIT'] = False
    g_params['DEBUG_CACHE'] = False
    g_params['SLEEP_INTERVAL'] = 5    # sleep interval in seconds
    g_params['MAX_SUBMIT_JOB_PER_NODE'] = 200
    g_params['MAX_KEEP_DAYS'] = 60
    g_params['MAX_RESUBMIT'] = 2
    g_params['MAX_SUBMIT_TRY'] = 3
    g_params['MAX_TIME_IN_REMOTE_QUEUE'] = 3600*24 # one day in seconds
    g_params['base_www_url'] = "http://proq3.bioinfo.se"
    g_params['FORMAT_DATETIME'] = "%Y-%m-%d %H:%M:%S %Z"
    g_params['STATUS_UPDATE_FREQUENCY'] = [500, 50]  # updated by if loop%$1 == $2
    g_params['MAXSIZE_MODEL_TO_SEND_BY_POST'] = 500*1024
    g_params['gen_logfile'] = gen_logfile
    g_params['gen_errfile'] = gen_errfile
    g_params['path_static']  = path_static
    g_params['path_log']  = path_log
    g_params['path_stat'] = path_stat
    g_params['name_server'] = "ProQ3"
    g_params['TZ'] = webcom.TZ
    return g_params
#}}}
if __name__ == '__main__' :
    g_params = InitGlobalParameter()

    date_str = time.strftime(g_params['FORMAT_DATETIME'])
    print("\n#%s#\n[Date: %s] qd_fe.py restarted"%('='*80,date_str))
    sys.stdout.flush()
    sys.exit(main(g_params))

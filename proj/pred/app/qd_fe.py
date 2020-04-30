#!/usr/bin/env python
# Description: daemon to submit jobs and retrieve results to/from remote
#              servers
# 
import os
import sys
import site

rundir = os.path.dirname(os.path.realpath(__file__))
webserver_root = os.path.realpath("%s/../../../"%(rundir))

activate_env="%s/env/bin/activate_this.py"%(webserver_root)
execfile(activate_env, dict(__file__=activate_env))
#Add the site-packages of the virtualenv
site.addsitedir("%s/env/lib/python2.7/site-packages/"%(webserver_root))
sys.path.append("%s/env/lib/python2.7/site-packages/"%(webserver_root))
sys.path.append("/usr/local/lib/python2.7/dist-packages")

import myfunc
import webserver_common as webcom
import time
from datetime import datetime
from pytz import timezone
import requests
import json
import urllib
import shutil
import hashlib
import subprocess
from suds.client import Client
import numpy

from geoip import geolite2
import pycountry

TZ = 'Europe/Stockholm'
os.environ['TZ'] = TZ
time.tzset()


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
    print >> sys.stderr, "Another instance of %s is running"%(progname)
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
    print >> fpout, usage_short
    print >> fpout, usage_ext
    print >> fpout, usage_exp#}}}

def get_job_status(jobid):#{{{
    status = "";
    rstdir = "%s/%s"%(path_result, jobid)
    starttagfile = "%s/%s"%(rstdir, "runjob.start")
    finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
    failedtagfile = "%s/%s"%(rstdir, "runjob.failed")
    if os.path.exists(failedtagfile):
        status = "Failed"
    elif os.path.exists(finishtagfile):
        status = "Finished"
    elif os.path.exists(starttagfile):
        status = "Running"
    elif os.path.exists(rstdir):
        status = "Wait"
    return status
#}}}
def get_total_seconds(td): #{{{
    """
    return the total_seconds for the timedate.timedelta object
    for python version >2.7 this is not needed
    """
    return (td.microseconds + (td.seconds + td.days * 24 * 3600) * 1e6) / 1e6
#}}}
def GetNumSuqJob(node):#{{{
    # get the number of queueing jobs on the node
    # return -1 if the url is not accessible
    url = "http://%s/cgi-bin/get_suqlist.cgi?base=log"%(node)
    try:
        rtValue = requests.get(url, timeout=2)
        if rtValue.status_code < 400:
            lines = rtValue.content.split("\n")
            cnt_queue_job = 0
            for line in lines:
                strs = line.split()
                if len(strs)>=4 and strs[0].isdigit():
                    status = strs[2]
                    if status == "Wait":
                        cnt_queue_job += 1
            return cnt_queue_job
        else:
            return -1
    except:
        webcom.loginfo("requests.get(%s) failed\n"%(url), gen_logfile)
        return -1

#}}}
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
def IsHaveAvailNode(cntSubmitJobDict):#{{{
    for node in cntSubmitJobDict:
        [num_queue_job, max_allowed_job] = cntSubmitJobDict[node]
        if num_queue_job < max_allowed_job:
            return True
    return False
#}}}
def GetNumModelSameUserDict(joblist):#{{{
# calculate the number of models for each user in the queue or running
    numModel_user_dict = {}
    for i in xrange(len(joblist)):
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

        for j in xrange(len(joblist)):
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

            status = get_job_status(jobid)

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

            li = [jobid, status, jobname, ip, email, numModel_str,
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
                current_time = datetime.now(timezone(TZ))
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
                                for i in xrange(len(itemList)):
                                    modelinfo.append(str(globalscore[itemList[i]]))

                            myfunc.WriteFile("\t".join(modelinfo)+"\n", finished_model_file, "a", True)
                except Exception as e:
                    msg = "Init scanning resut folder for jobid %s failed with message \"%s\""%(jobid, str(e))
                    webcom.loginfo(msg, gen_logfile)
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
    cnttry_idx_file = "%s/cntsubmittry_seqindex.txt"%(rstdir)#index file to keep log of tries
    torun_idx_str_list = []

    if not os.path.exists(numModelFile) or os.stat(numModelFile).st_size < 1:
        myfunc.WriteFile(str(numModel), numModelFile, "w", True)
    for ii in xrange(len(modelList)):
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
            except Exception as e:
                date_str = time.strftime(g_params['FORMAT_DATETIME'])
                msg = "Failed to run PDB2Seq, wrong PDB format for the model structure. errmsg=%s"%(str(e))
                myfunc.WriteFile("[%s] %s\n"%(date_str, msg), runjob_errfile, "a", True)
                myfunc.WriteFile("%d\n"%(ii), failed_idx_file, "a", True)
                webcom.WriteDateTimeTagFile(starttagfile, runjob_logfile, runjob_errfile)
                isFailed = True
        if not isFailed:
            torun_idx_str_list.append(str(ii))

    torun_idx_file = "%s/torun_seqindex.txt"%(rstdir) # model index to be run
    myfunc.WriteFile("\n".join(torun_idx_str_list)+"\n", torun_idx_file, "w", True)

    # write cnttry file for each jobs to run
    cntTryDict = {}
    for idx in range(numModel):
        cntTryDict[idx] = 0
    json.dump(cntTryDict, open(cnttry_idx_file, "w"))

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
    numModelFile = "%s/query.numModel.txt"%(rstdir)
    numModel = int(myfunc.ReadFile(numModelFile).strip())

    cntTryDict = webcom.InitCntTryDict(cnttry_idx_file, numModel)


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
                webcom.loginfo("Failed to access %s\n"%(wsdl_url),gen_logfile)
                break

            [cnt, maxnum] = cntSubmitJobDict[node]
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
                md5_key = hashlib.md5(seq).hexdigest()
                subfoldername = md5_key[:2]

                isSubmitSuccess = False
                if wsdl_url.find("commonbackend") != -1:
                    query_para['name_software'] = "docker_proq3"
                else:
                    query_para['name_software'] = "docker_proq3"

                if query_para['isForceRun']:
                    query_para['url_profile'] = ""
                else:
                    query_para['url_profile'] = "http://proq3.bioinfo.se/static/result/profilecache/%s/%s.zip"%(subfoldername,  md5_key) 

                query_para['url_pdb_model'] = "http://proq3.bioinfo.se/static/result/%s/%s/%s"%(jobid, os.path.basename(tmpdir.rstrip('/')), os.path.basename(modelfile_this_model))
                #query_para['pdb_model'] = model
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
                    myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_logfile, "a", True)
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
                        myfunc.WriteFile("[Date: %s] bad wsdl return value\n"%(date_str), gen_logfile, "a", True)
                if isSubmitSuccess:
                    cntTryDict[origIndex] += 1  #cntTryDict increment by 1
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
            cntSubmitJobDict[node] = [cnt, maxnum]

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

    # update the cnttry_idx_file
    with open(cnttry_idx_file, 'w') as fpout:
        json.dump(cntTryDict, fpout)

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

    cntTryDict = webcom.InitCntTryDict(cnttry_idx_file, numModel)

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
            all_idx_list = [str(x) for x in xrange(numModel)]
            torun_idx_str_list = list(set(all_idx_list)-completed_idx_set)
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
    for i in xrange(len(lines)):
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
            webcom.loginfo("Failed to access %s\n"%(wsdl_url), gen_logfile)
            pass


    for i in xrange(len(lines)):#{{{
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
            keep_queueline_list.append(line)
            continue
        try:
            rtValue = myclient.service.checkjob(remote_jobid)
        except Exception as e:
            webcom.loginfo("Failed to run myclient.service.checkjob(%s), with errmsg=%s\n"%(remote_jobid, str(e)), gen_logfile)
            rtValue = []
            pass
        isSuccess = False
        isFinish_remote = False
        status = ""
        if len(rtValue) >= 1:
            ss2 = rtValue[0]
            if len(ss2)>=3:
                status = ss2[0]
                result_url = ss2[1]
                errinfo = ss2[2]
                if g_params['DEBUG']:
                    msg = "checkjob(%s), status=\"%s\", errinfo = \"%s\""%(remote_jobid, status, errinfo)
                    webcom.loginfo(msg, gen_logfile)

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
                            urllib.urlretrieve (result_url, outfile_zip)
                            isRetrieveSuccess = True
                            myfunc.WriteFile(" succeeded\n", gen_logfile, "a", True)
                        except Exception,e:
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
                                msg = "Failed to copy %s to %s. message = \"%s\""%(
                                        profile_this_model, outpath_profile, str(e))
                                webcom.loginfo(msg, gen_logfile)

                        seqfile_of_profile = "%s/query.fasta"%(profile_this_model)
                        (t_seqid, t_seqanno, t_seq) = myfunc.ReadSingleFasta(seqfile_of_profile)
                        md5_key = hashlib.md5(t_seq).hexdigest()
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

                            try:
                                shutil.copyfile("%s.zip"%(md5_key), zipfile_profilecache)
                                msg = "copyfile %s.zip -> %s"%(md5_key, zipfile_profilecache)
                                webcom.loginfo(msg, gen_logfile)
                            except Exception as e:
                                msg = "copyfile %s.zip -> %s failed with message %s"%(
                                        md5_key, zipfile_profilecache, str(e))
                                webcom.loginfo(msg, gen_logfile)

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
                            try:
                                rtValue2 = myclient.service.deletejob(remote_jobid)
                            except:
                                webcom.loginfo("Failed to run myclient.service.deletejob(%s)\n"%(remote_jobid), gen_logfile)
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

                            # delete the zip file
                            os.remove(outfile_zip)
                            shutil.rmtree("%s/%s"%(tmpdir, remote_jobid))

#}}}
                elif status in ["Failed", "None"]:
                    # the job is failed for this sequence, try to re-submit
                    isFinish_remote = True
                    cnttry = 1
                    try:
                        cnttry = int(cntTryDict[int(origIndex)])
                    except KeyError:
                        cnttry = 1
                    if cnttry <= g_params['MAX_RESUBMIT']:
                        resubmit_idx_list.append(str(origIndex))
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
                for i in xrange(len(itemList)):
                    modelinfo.append(str(globalscore[itemList[i]]))

            myfunc.WriteFile("\t".join(modelinfo)+"\n", finished_model_file, "a", True)

            finished_idx_list.append(str(origIndex))#}}}

        if not isFinish_remote:
            time_in_remote_queue = time.time() - submit_time_epoch
            # for jobs queued in the remote queue more than one day (but not
            # running) delete it and try to resubmit it. This solved the
            # problem of dead jobs in the remote server due to server
            # rebooting)
            if status != "Running" and status != "" and time_in_remote_queue > g_params['MAX_TIME_IN_REMOTE_QUEUE']:
                # delete the remote job on the remote server
                try:
                    rtValue2 = myclient.service.deletejob(remote_jobid)
                except Exception as e:
                    webcom.loginfo("Failed to run myclient.service.deletejob(%s) on node %s with msg %s\n"%(remote_jobid, node, str(e)), gen_logfile)
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
        keep_queueline_list = list(set(keep_queueline_list))
        myfunc.WriteFile("\n".join(keep_queueline_list)+"\n", remotequeue_idx_file, "w", True);
    else:
        myfunc.WriteFile("", remotequeue_idx_file, "w", True);


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
            msg = "Number of input model is zero"
            webcom.loginfo(msg, runjob_errfile, "a", True)
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
            for ii in xrange(numModel):
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

            msg = "Compress the result folder to zipfile %s"%(zipfile_fullpath)
            webcom.loginfo(msg, gen_logfile)
            os.chdir(rstdir)
            cmd = ["zip", "-rq", zipfile, jobid]
            webcom.RunCmd(cmd, gen_logfile, gen_errfile)
            os.chdir(cwd)

            if len(failed_idx_list)>0:
                myfunc.WriteDateTimeTagFile(failedtagfile, runjob_logfile, runjob_errfile)

            if finish_status == "success":
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
                msg = "Sendmail %s -> %s, %s"%(from_email, to_email, subject)
                webcom.loginfo(msg, gen_logfile)
                rtValue = myfunc.Sendmail(from_email, to_email, subject, bodytext)
                if rtValue != 0:
                    msg = "Sendmail to {} failed with status {}".format(to_email, rtValue),
                    webcom.loginfo(msg, gen_logfile)
                msg = "Send notification to %s"%(to_email)
                webcom.loginfo(msg, gen_logfile)

            # send the repacked pdb models to CAMEO
            if submitter in ["CAMEO", "VIP"]:
                to_email_list = [email] + g_params['forward_email_list']
                for to_email in to_email_list:
                    subject = GetEmailSubject_CAMEO(query_para)
                    bodytext = GetEmailBody_CAMEO(jobid, query_para)
                    msg = "Sendmail %s -> %s, %s"%(from_email, to_email, subject)
                    webcom.loginfo(msg, gen_logfile)

                    rtValue = myfunc.Sendmail(from_email, to_email, subject, bodytext)
                    if rtValue != 0:
                        msg = "Sendmail to {} failed with status {}".format(to_email, rtValue),
                        webcom.loginfo(msg, gen_logfile)
                    msg = "Send CAMEO_result to %s"%(to_email)
                    webcom.loginfo(msg, gen_logfile)

#}}}
#}}}
def RunStatistics(path_result, path_log):#{{{
# 1. calculate average running time, only for those sequences with time.txt
# show also runtime of type and runtime -vs- seqlength
    myfunc.WriteFile("RunStatistics...\n", gen_logfile, "a", True)
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
        finished_model_file = "%s/finished_models.txt"%(outpath_result)
        lines = []
        if os.path.exists(finished_model_file):
            lines = myfunc.ReadFile(finished_model_file).split("\n")
        for line in lines:
            strs = line.split("\t")
            if len(strs)>=7:
                str_seqlen = strs[1]
                str_loc_def = strs[2]
                str_loc_def_score = strs[3]
                source = strs[4]
                if source == "newrun":
                    subfolder = strs[0]
                    timefile = "%s/%s/%s"%(outpath_result, subfolder, "time.txt")
                    if os.path.exists(timefile) and os.path.getsize(timefile)>0:
                        txt = myfunc.ReadFile(timefile).strip()
                        try:
                            ss2 = txt.split(";")
                            runtime_str = ss2[1]
                            if len(ss2) >= 3:
                                database_mode = ss2[2]
                            else:
                                 #set default value of database_mode if it is not available in the timefile
                                database_mode = "PRODRES"  
                            runtimeloginfolist.append("\t".join([jobid, subfolder,
                                source, runtime_str, database_mode, str_seqlen,
                                str_loc_def, str_loc_def_score]))
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
                start_date = webcom.datetime_str_to_time(start_date_str)
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
    li_countjob = sorted(countjob_country.items(), key=lambda x:x[1][0], reverse=True) 
    li_str = []
    li_str.append("#Country\tNumSeq\tNumJob\tNumIP")
    for li in li_countjob:
        li_str.append("%s\t%d\t%d\t%d"%(li[0], li[1][0], li[1][1], len(li[1][2])))
    myfunc.WriteFile("\n".join(li_str)+"\n", outfile_countjob_by_country, "w", True)

    flist = [outfile_numseqjob, outfile_numseqjob_web, outfile_numseqjob_wsdl  ]
    dictlist = [countjob_numseq_dict, countjob_numseq_dict_web, countjob_numseq_dict_wsdl]
    for i in xrange(len(flist)):
        dt = dictlist[i]
        outfile = flist[i]
        sortedlist = sorted(dt.items(), key = lambda x:x[0])
        try:
            fpout = open(outfile,"w")
            for j in xrange(len(sortedlist)):
                nseq = sortedlist[j][0]
                count = sortedlist[j][1]
                fpout.write("%d\t%d\n"%(nseq,count))
            fpout.close()
            if os.path.getsize(outfile) > 0:
                cmd = ["%s/app/plot_numseq_of_job.sh"%(basedir), outfile]
                webcom.RunCmd(cmd, gen_logfile, gen_errfile)
        except IOError:
            continue
    if os.path.getsize(outfile_numseqjob_wsdl) > 0:
        cmd = ["%s/app/plot_numseq_of_job_mtp.sh"%(basedir), "-web",
                outfile_numseqjob_web, "-wsdl", outfile_numseqjob_wsdl]
        webcom.RunCmd(cmd, gen_logfile, gen_errfile)

# output waittime vs numseq_of_job
# output finishtime vs numseq_of_job
    outfile_waittime_nseq = "%s/waittime_nseq.stat.txt"%(path_stat)
    outfile_waittime_nseq_web = "%s/waittime_nseq_web.stat.txt"%(path_stat)
    outfile_waittime_nseq_wsdl = "%s/waittime_nseq_wsdl.stat.txt"%(path_stat)
    outfile_finishtime_nseq = "%s/finishtime_nseq.stat.txt"%(path_stat)
    outfile_finishtime_nseq_web = "%s/finishtime_nseq_web.stat.txt"%(path_stat)
    outfile_finishtime_nseq_wsdl = "%s/finishtime_nseq_wsdl.stat.txt"%(path_stat)

    outfile_avg_waittime_nseq = "%s/avg_waittime_nseq.stat.txt"%(path_stat)
    outfile_avg_waittime_nseq_web = "%s/avg_waittime_nseq_web.stat.txt"%(path_stat)
    outfile_avg_waittime_nseq_wsdl = "%s/avg_waittime_nseq_wsdl.stat.txt"%(path_stat)
    outfile_avg_finishtime_nseq = "%s/avg_finishtime_nseq.stat.txt"%(path_stat)
    outfile_avg_finishtime_nseq_web = "%s/avg_finishtime_nseq_web.stat.txt"%(path_stat)
    outfile_avg_finishtime_nseq_wsdl = "%s/avg_finishtime_nseq_wsdl.stat.txt"%(path_stat)

    outfile_median_waittime_nseq = "%s/median_waittime_nseq.stat.txt"%(path_stat)
    outfile_median_waittime_nseq_web = "%s/median_waittime_nseq_web.stat.txt"%(path_stat)
    outfile_median_waittime_nseq_wsdl = "%s/median_waittime_nseq_wsdl.stat.txt"%(path_stat)
    outfile_median_finishtime_nseq = "%s/median_finishtime_nseq.stat.txt"%(path_stat)
    outfile_median_finishtime_nseq_web = "%s/median_finishtime_nseq_web.stat.txt"%(path_stat)
    outfile_median_finishtime_nseq_wsdl = "%s/median_finishtime_nseq_wsdl.stat.txt"%(path_stat)

    flist1 = [ outfile_waittime_nseq , outfile_waittime_nseq_web ,
            outfile_waittime_nseq_wsdl , outfile_finishtime_nseq ,
            outfile_finishtime_nseq_web , outfile_finishtime_nseq_wsdl
            ]

    flist2 = [ outfile_avg_waittime_nseq , outfile_avg_waittime_nseq_web ,
            outfile_avg_waittime_nseq_wsdl , outfile_avg_finishtime_nseq ,
            outfile_avg_finishtime_nseq_web , outfile_avg_finishtime_nseq_wsdl
            ]
    flist3 = [ outfile_median_waittime_nseq , outfile_median_waittime_nseq_web ,
            outfile_median_waittime_nseq_wsdl , outfile_median_finishtime_nseq ,
            outfile_median_finishtime_nseq_web , outfile_median_finishtime_nseq_wsdl
            ]

    dict_list = [
            waittime_numseq_dict , waittime_numseq_dict_web , waittime_numseq_dict_wsdl , finishtime_numseq_dict , finishtime_numseq_dict_web , finishtime_numseq_dict_wsdl
            ]

    for i in xrange(len(flist1)):
        dt = dict_list[i]
        outfile1 = flist1[i]
        outfile2 = flist2[i]
        outfile3 = flist3[i]
        sortedlist = sorted(dt.items(), key = lambda x:x[0])
        try:
            fpout = open(outfile1,"w")
            for j in xrange(len(sortedlist)):
                nseq = sortedlist[j][0]
                li_time = sortedlist[j][1]
                for k in xrange(len(li_time)):
                    fpout.write("%d\t%f\n"%(nseq,li_time[k]))
            fpout.close()
        except IOError:
            pass
        try:
            fpout = open(outfile2,"w")
            for j in xrange(len(sortedlist)):
                nseq = sortedlist[j][0]
                li_time = sortedlist[j][1]
                avg_time = myfunc.FloatDivision(sum(li_time), len(li_time))
                fpout.write("%d\t%f\n"%(nseq,avg_time))
            fpout.close()
        except IOError:
            pass
        try:
            fpout = open(outfile3,"w")
            for j in xrange(len(sortedlist)):
                nseq = sortedlist[j][0]
                li_time = sortedlist[j][1]
                median_time = numpy.median(li_time)
                fpout.write("%d\t%f\n"%(nseq,median_time))
            fpout.close()
        except IOError:
            pass

    flist = flist1
    for i in xrange(len(flist)):
        outfile = flist[i]
        if os.path.exists(outfile):
            cmd = ["%s/app/plot_nseq_waitfinishtime.sh"%(basedir), outfile]
            webcom.RunCmd(cmd, gen_logfile, gen_errfile)
    flist = flist2+flist3
    for i in xrange(len(flist)):
        outfile = flist[i]
        if os.path.exists(outfile):
            cmd = ["%s/app/plot_avg_waitfinishtime.sh"%(basedir), outfile]
            webcom.RunCmd(cmd, gen_logfile, gen_errfile)

# get longest predicted seq
# get query with most TM helics
# get query takes the longest time
    extreme_runtimelogfile = "%s/stat/extreme_jobruntime.log"%(path_log)

    longestlength = -1
    mostTM = -1
    longestruntime = -1.0
    line_longestlength = ""
    line_mostTM = ""
    line_longestruntime = ""

#3. get running time vs sequence length
    cntseq = 0
    cnt_hasSP = 0
    outfile_runtime = "%s/length_runtime.stat.txt"%(path_stat)
    outfile_runtime_pfam = "%s/length_runtime.pfam.stat.txt"%(path_stat)
    outfile_runtime_cdd = "%s/length_runtime.cdd.stat.txt"%(path_stat)
    outfile_runtime_uniref = "%s/length_runtime.uniref.stat.txt"%(path_stat)
    outfile_runtime_avg = "%s/length_runtime.stat.avg.txt"%(path_stat)
    outfile_runtime_pfam_avg = "%s/length_runtime.pfam.stat.avg.txt"%(path_stat)
    outfile_runtime_cdd_avg = "%s/length_runtime.cdd.stat.avg.txt"%(path_stat)
    outfile_runtime_uniref_avg = "%s/length_runtime.uniref.stat.avg.txt"%(path_stat)
    li_length_runtime = []
    li_length_runtime_pfam = []
    li_length_runtime_cdd = []
    li_length_runtime_uniref = []
    dict_length_runtime = {}
    dict_length_runtime_pfam = {}
    dict_length_runtime_cdd = {}
    dict_length_runtime_uniref = {}
    li_length_runtime_avg = []
    li_length_runtime_pfam_avg = []
    li_length_runtime_cdd_avg = []
    li_length_runtime_uniref_avg = []

    if os.path.exists(runtimelogfile):
        hdl = myfunc.ReadLineByBlock(runtimelogfile)
        if not hdl.failure:
            lines = hdl.readlines()
            while lines != None:
                for line in lines:
                    strs = line.split("\t")
                    if len(strs) < 8:
                        continue
                    jobid = strs[0]
                    seqidx = strs[1]
                    runtime = -1.0
                    try:
                        runtime = float(strs[3])
                    except:
                        pass
                    mtd_profile = strs[4]
                    lengthseq = -1
                    try:
                        lengthseq = int(strs[5])
                    except:
                        pass

                    numTM = -1
                    try:
                        numTM = int(strs[6])
                    except:
                        pass
                    isHasSP = strs[7]

                    cntseq += 1
                    if isHasSP == "True":
                        cnt_hasSP += 1

                    if runtime > longestruntime:
                        line_longestruntime = line
                        longestruntime = runtime
                    if lengthseq > longestlength:
                        line_longestseq = line
                        longestlength = lengthseq
                    if numTM > mostTM:
                        mostTM = numTM
                        line_mostTM = line

                    if lengthseq != -1:
                        li_length_runtime.append([lengthseq, runtime])
                        if lengthseq not in dict_length_runtime:
                            dict_length_runtime[lengthseq] = []
                        dict_length_runtime[lengthseq].append(runtime)
                        if mtd_profile == "pfam":
                            li_length_runtime_pfam.append([lengthseq, runtime])
                            if lengthseq not in dict_length_runtime_pfam:
                                dict_length_runtime_pfam[lengthseq] = []
                            dict_length_runtime_pfam[lengthseq].append(runtime)
                        elif mtd_profile == "cdd":
                            li_length_runtime_cdd.append([lengthseq, runtime])
                            if lengthseq not in dict_length_runtime_cdd:
                                dict_length_runtime_cdd[lengthseq] = []
                            dict_length_runtime_cdd[lengthseq].append(runtime)
                        elif mtd_profile == "uniref":
                            li_length_runtime_uniref.append([lengthseq, runtime])
                            if lengthseq not in dict_length_runtime_uniref:
                                dict_length_runtime_uniref[lengthseq] = []
                            dict_length_runtime_uniref[lengthseq].append(runtime)
                lines = hdl.readlines()
            hdl.close()

        li_content = []
        try:
            for line in [line_mostTM, line_longestseq, line_longestruntime]:
                li_content.append(line)
            myfunc.WriteFile("\n".join(li_content)+"\n", extreme_runtimelogfile, "w", True)
        except:
            pass

    # get lengthseq -vs- average_runtime
    dict_list = [dict_length_runtime, dict_length_runtime_pfam, dict_length_runtime_cdd, dict_length_runtime_uniref]
    li_list = [li_length_runtime_avg, li_length_runtime_pfam_avg, li_length_runtime_cdd_avg, li_length_runtime_uniref_avg]
    li_sum_runtime = [0.0]*len(dict_list)
    for i in xrange(len(dict_list)):
        dt = dict_list[i]
        li = li_list[i]
        for lengthseq in dt:
            avg_runtime = sum(dt[lengthseq])/float(len(dt[lengthseq]))
            li.append([lengthseq, avg_runtime])
            li_sum_runtime[i] += sum(dt[lengthseq])

    avg_runtime = myfunc.FloatDivision(li_sum_runtime[0], len(li_length_runtime))
    avg_runtime_pfam = myfunc.FloatDivision(li_sum_runtime[1], len(li_length_runtime_pfam))
    avg_runtime_cdd = myfunc.FloatDivision(li_sum_runtime[2], len(li_length_runtime_cdd))
    avg_runtime_uniref = myfunc.FloatDivision(li_sum_runtime[3], len(li_length_runtime_uniref))

    li_list = [li_length_runtime, li_length_runtime_pfam,
            li_length_runtime_cdd, li_length_runtime_uniref,
            li_length_runtime_avg, li_length_runtime_pfam_avg,
            li_length_runtime_cdd_avg, li_length_runtime_uniref_avg]
    flist = [outfile_runtime, outfile_runtime_pfam, outfile_runtime_cdd,
            outfile_runtime_uniref, outfile_runtime_avg,
            outfile_runtime_pfam_avg, outfile_runtime_cdd_avg,
            outfile_runtime_uniref_avg]
    for i in xrange(len(flist)):
        outfile = flist[i]
        li = li_list[i]
        sortedlist = sorted(li, key=lambda x:x[0])
        try:
            fpout = open(outfile,"w")
            for j in xrange(len(sortedlist)):
                lengthseq = sortedlist[j][0]
                runtime = sortedlist[j][1]
                fpout.write("%d\t%f\n"%(lengthseq,runtime))
            fpout.close()
        except IOError:
            continue

    outfile_avg_runtime = "%s/avg_runtime.stat.txt"%(path_stat)
    try:
        fpout = open(outfile_avg_runtime,"w")
        fpout.write("%s\t%f\n"%("All",avg_runtime))
        fpout.write("%s\t%f\n"%("Pfam",avg_runtime_pfam))
        fpout.write("%s\t%f\n"%("CDD",avg_runtime_cdd))
        fpout.write("%s\t%f\n"%("Uniref",avg_runtime_uniref))
        fpout.close()
    except IOError:
        pass
    if os.path.exists(outfile_avg_runtime):
        cmd = ["%s/app/plot_avg_runtime.sh"%(basedir), outfile_avg_runtime]
        webcom.RunCmd(cmd, gen_logfile, gen_errfile)

    flist = [outfile_runtime, outfile_runtime_pfam, outfile_runtime_cdd,
            outfile_runtime_uniref]
    for outfile in flist:
        if os.path.exists(outfile):
            cmd = ["%s/app/plot_length_runtime.sh"%(basedir), outfile]
            webcom.RunCmd(cmd, gen_logfile, gen_errfile)

    if os.path.exists(outfile_runtime_cdd):
        cmd = ["%s/app/plot_length_runtime_mtp.sh"%(basedir), "-pfam",
                outfile_runtime_pfam, "-cdd", outfile_runtime_cdd, "-uniref",
                outfile_runtime_uniref, "-sep-avg"]
        webcom.RunCmd(cmd, gen_logfile, gen_errfile)


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
                except Exception as e:
                    isValidSubmitDate = False
                if isValidSubmitDate:#{{{
                    day_str = submit_date_str.split()[0]
                    (beginning_of_week, end_of_week) = myfunc.week_beg_end(submit_date)
                    week_str = beginning_of_week.strftime("%Y-%m-%d")
                    month_str = submit_date.strftime("%Y-%b")
                    year_str = submit_date.year
                    day = int(day_str.replace("-", ""))
                    week = int(submit_date.strftime("%Y%V"))
                    month = int(submit_date.strftime("%Y%m"))
                    year = int(year_str)
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

    for i in xrange(len(dict_list)):
        dt = dict_list[i]
        sortedlist = sorted(dt.items(), key = lambda x:x[0])
        for j in range(3):
            li = li_list[j*4+i]
            k1 = j*2 +1
            k2 = j*2 +2
            for kk in xrange(len(sortedlist)):
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
    for i in xrange(len(flist)):
        outfile = flist[i]
        li = li_list[i]
        try:
            fpout = open(outfile,"w")
            for j in xrange(len(li)):     # name    njob   nseq
                fpout.write("%s\t%d\t%d\n"%(li[j][0], li[j][1], li[j][2]))
            fpout.close()
        except IOError:
            pass
        if os.path.exists(outfile):
            cmd = ["%s/app/plot_numsubmit.sh"%(basedir), outfile]
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
        isOldRstdirDeleted = False
        if loop % 500 == 50:
            RunStatistics(path_result, path_log)
            isOldRstdirDeleted = webcom.DeleteOldResult(path_result, path_log, gen_logfile, MAX_KEEP_DAYS=g_params['MAX_KEEP_DAYS'])
            webcom.CleanServerFile(gen_logfile, gen_errfile)
        webcom.ArchiveLogFile(path_log, threshold_logfilesize=threshold_logfilesize) 

        base_www_url_file = "%s/static/log/base_www_url.txt"%(basedir)
        if os.path.exists(base_www_url_file):
            g_params['base_www_url'] = myfunc.ReadFile(base_www_url_file).strip()
        if g_params['base_www_url'] == "":
            g_params['base_www_url'] = "http://proq3.bioinfo.se"

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

        avail_computenode_list = myfunc.ReadIDList2(computenodefile, col=0)
        g_params['vip_user_list'] = myfunc.ReadIDList2(vip_email_file, col=0)
        g_params['forward_email_list'] = myfunc.ReadIDList2(forward_email_file, col=0)
        num_avail_node = len(avail_computenode_list)

        webcom.loginfo("loop %d"%(loop), gen_logfile)

        CreateRunJoblog(path_result, submitjoblogfile, runjoblogfile,
                finishedjoblogfile, loop, isOldRstdirDeleted)

        # Get number of jobs submitted to the remote server based on the
        # runjoblogfile
        runjobidlist = myfunc.ReadIDList2(runjoblogfile,0)
        remotequeueDict = {}
        for node in avail_computenode_list:
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
        for node in avail_computenode_list:
            #num_queue_job = GetNumSuqJob(node)
            num_queue_job = len(remotequeueDict[node])
            if num_queue_job >= 0:
                cntSubmitJobDict[node] = [num_queue_job,
                        g_params['MAX_SUBMIT_JOB_PER_NODE']] #[num_queue_job, max_allowed_job]
            else:
                cntSubmitJobDict[node] = [g_params['MAX_SUBMIT_JOB_PER_NODE'],
                        g_params['MAX_SUBMIT_JOB_PER_NODE']] #[num_queue_job, max_allowed_job]

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

                        webcom.loginfo("CompNodeStatus: %s\n"%(str(cntSubmitJobDict)), gen_logfile)

                        runjob_lockfile = "%s/%s/%s.lock"%(path_result, jobid, "runjob.lock")
                        if os.path.exists(runjob_lockfile):
                            msg = "runjob_lockfile %s exists, ignore the job %s" %(runjob_lockfile, jobid)
                            webcom.loginfo(msg, gen_logfile)
                            continue

                        if IsHaveAvailNode(cntSubmitJobDict) and not g_params['DEBUG_NO_SUBMIT']:
                            SubmitJob(jobid, cntSubmitJobDict, numModel_this_user, query_para)
                        GetResult(jobid, query_para) # the start tagfile is written when got the first result
                        CheckIfJobFinished(jobid, numseq, email, query_para)

                lines = hdl.readlines()
            hdl.close()

        webcom.loginfo("sleep for %d seconds\n"%(g_params['SLEEP_INTERVAL']), gen_logfile)
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
    return g_params
#}}}
if __name__ == '__main__' :
    g_params = InitGlobalParameter()
    date_str = time.strftime(g_params['FORMAT_DATETIME'])
    print("\n#%s#\n[Date: %s] qd_fe.py restarted"%('='*80,date_str))
    sys.stdout.flush()
    sys.exit(main(g_params))


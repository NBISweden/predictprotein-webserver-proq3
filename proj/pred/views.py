# ChangeLog

import os, sys
import tempfile
import re
import subprocess
from datetime import datetime
from dateutil import parser as dtparser
from pytz import timezone
import time
import math
import shutil
import json
from libpredweb import myfunc
from libpredweb import webserver_common as webcom

TZ = webcom.TZ
os.environ['TZ'] = TZ
time.tzset()

# for dealing with IP address and country names
from geoip import geolite2
import pycountry

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.views.decorators.csrf import csrf_exempt  

# for user authentication
from django.contrib.auth import authenticate, login, logout

# import variables from settings
from django.conf import settings

SITE_ROOT = os.path.dirname(os.path.realpath(__file__))
progname =  os.path.basename(__file__)
rootname_progname = os.path.splitext(progname)[0]
path_app = "%s/app"%(SITE_ROOT)
sys.path.append(path_app)

path_log = "%s/static/log"%(SITE_ROOT)
path_static = "%s/static"%(SITE_ROOT)
path_stat = "%s/stat"%(path_log)
path_result = "%s/static/result"%(SITE_ROOT)
gen_logfile = "%s/static/log/%s.log"%(SITE_ROOT, progname)
path_md5 = "%s/static/md5"%(SITE_ROOT)
path_tmp = "%s/static/tmp"%(SITE_ROOT)

python_exec = "python"


# global parameters
g_params = {}
g_params['BASEURL'] = "/pred/";
g_params['MAXSIZE_UPLOAD_MODELFILE_IN_MB']  = 10
g_params['MAXSIZE_UPLOAD_SEQFILE_IN_MB'] = 0.15
g_params['MAXSIZE_UPLOAD_MODELFILE_IN_BYTE'] = g_params['MAXSIZE_UPLOAD_MODELFILE_IN_MB'] * 1024*1024
g_params['MAXSIZE_UPLOAD_SEQFILE_IN_BYTE'] = g_params['MAXSIZE_UPLOAD_SEQFILE_IN_MB'] * 1024*1024
g_params['MAX_DAYS_TO_SHOW'] = 100000
g_params['BIG_NUMBER'] = 100000
g_params['MAX_NUMSEQ_FOR_FORCE_RUN'] = 100
g_params['MAX_ALLOWD_NUMMODEL'] = 5
g_params['MIN_LEN_SEQ'] = 1
g_params['MAX_LEN_SEQ'] = 1000000
g_params['MAX_NUMSEQ_PER_JOB'] = 1 #the target sequence can have only one sequence
g_params['FORMAT_DATETIME'] = webcom.FORMAT_DATETIME
g_params['DEBUG'] = False
g_params['STATIC_URL'] = settings.STATIC_URL
g_params['SUPER_USER_LIST'] = settings.SUPER_USER_LIST
g_params['path_static'] = path_static
g_params['path_stat'] = path_stat
g_params['SITE_ROOT'] = SITE_ROOT
g_params['path_result'] = path_result
g_params['MAX_ACTIVE_USER'] = 10


qd_fe_scriptfile = "%s/qd_fe.py"%(path_app)
gen_errfile = "%s/static/log/%s.err"%(SITE_ROOT, progname)
gen_logfile = "%s/static/log/%s.log"%(SITE_ROOT, progname)

# Create your views here.
from django.shortcuts import render
from django.http import HttpResponse
from django.http import HttpRequest
from django.http import HttpResponseRedirect
from django.views.static import serve


#from pred.models import Query
from proj.pred.models import SubmissionForm
from proj.pred.models import FieldContainer
from django.template import Context, loader


def index(request):#{{{
    path_tmp = "%s/static/tmp"%(SITE_ROOT)
    path_md5 = "%s/static/md5"%(SITE_ROOT)
    if not os.path.exists(path_result):
        os.mkdir(path_result, 0o755)
    if not os.path.exists(path_result):
        os.mkdir(path_tmp, 0o755)
    if not os.path.exists(path_md5):
        os.mkdir(path_md5, 0o755)
    base_www_url_file = "%s/static/log/base_www_url.txt"%(SITE_ROOT)
    if not os.path.exists(base_www_url_file):
        base_www_url = webcom.get_url_scheme(request) + request.META['HTTP_HOST']
        myfunc.WriteFile(base_www_url, base_www_url_file, "w", True)

    # read the local config file if exists
    configfile = "%s/config/config.json"%(SITE_ROOT)
    config = {}
    if os.path.exists(configfile):
        text = myfunc.ReadFile(configfile)
        config = json.loads(text)

    if rootname_progname in config:
        g_params.update(config[rootname_progname])
        g_params['MAXSIZE_UPLOAD_SEQFILE_IN_BYTE'] = g_params['MAXSIZE_UPLOAD_SEQFILE_IN_MB'] * 1024*1024
        g_params['MAXSIZE_UPLOAD_MODELFILE_IN_BYTE'] = g_params['MAXSIZE_UPLOAD_MODELFILE_IN_MB'] * 1024*1024

    return submit_seq(request)
#}}}
def submit_seq(request):#{{{
    info = {}
    webcom.set_basic_config(request, info, g_params)

    # if this is a POST request we need to process the form data
    if request.method == 'POST':
        # create a form instance and populate it with data from the request:
        form = SubmissionForm(request.POST)
        # check whether it's valid:
        if form.is_valid():
            # process the data in form.cleaned_data as required
            # redirect to a new URL:

            jobname = request.POST['jobname']
            email = request.POST['email']
            method_quality = request.POST['method_quality']
            try:
                targetlength = int(request.POST['targetlength'])
            except ValueError:
                targetlength = None

            rawseq = request.POST['rawseq'] + "\n" # force add a new line
            rawmodel = request.POST['rawmodel'].replace('\r','') + "\n" # force add a new line
            isForceRun = False
            isKeepFiles = True
            isRepack = True
            isDeepLearning = False

            if 'forcerun' in request.POST:
                isForceRun = True

#             if 'keepfile' in request.POST:
#                 isKeepFiles = True

            if 'repacking' in request.POST:
                isRepack = True
            else:
                isRepack = False

            if 'deep' in request.POST:
                isDeepLearning = True
            else:
                isDeepLearning = False

            for tup in form.method_quality_choices:
                if tup[0] == method_quality:
                    method_quality = tup[1]
                    break

            try:
                seqfile = request.FILES['seqfile']
            except KeyError as MultiValueDictKeyError:
                seqfile = ""
            try:
                modelfile = request.FILES['modelfile']
            except KeyError as MultiValueDictKeyError:
                modelfile = ""
            date_str = time.strftime(g_params['FORMAT_DATETIME'])
            query = {}
            query['rawseq'] = rawseq
            query['rawmodel'] = rawmodel
            query['seqfile'] = seqfile
            query['modelfile'] = modelfile
            query['targetlength'] = targetlength
            query['email'] = email
            query['jobname'] = jobname
            query['method_quality'] = method_quality
            query['date'] = date_str
            query['client_ip'] = info['client_ip']
            query['errinfo'] = ""
            query['method_submission'] = "web"
            query['isForceRun'] = isForceRun
            query['username'] = info['username']
            query['isKeepFiles'] = isKeepFiles
            query['isRepack'] = isRepack
            query['isDeepLearning'] = isDeepLearning
            query['STATIC_URL'] = settings.STATIC_URL

            is_valid = ValidateQuery(request, query)

            if is_valid:
                jobid = RunQuery(request, query)

                # type of method_submission can be web or wsdl
                #date, jobid, IP, numseq, size, jobname, email, method_submission
                log_record = "%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n"%(query['date'], jobid,
                        query['client_ip'], query['nummodel'],
                        len(query['rawmodel']),query['jobname'], query['email'],
                        query['method_submission'])
                main_logfile_query = "%s/%s/%s"%(SITE_ROOT, "static/log", "submitted_seq.log")
                myfunc.WriteFile(log_record, main_logfile_query, "a", True)

                divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                        "static/log/divided", "%s_submitted_seq.log"%(info['client_ip']))
                divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                        "static/log/divided", "%s_finished_job.log"%(info['client_ip']))
                if info['client_ip'] != "":
                    myfunc.WriteFile(log_record, divided_logfile_query, "a", True)


                file_seq_warning = "%s/%s/%s/%s"%(SITE_ROOT, "static/result", jobid, "query.warn.txt")
                query['file_seq_warning'] = os.path.basename(file_seq_warning)
                if query['warninfo'] != "":
                    myfunc.WriteFile(query['warninfo'], file_seq_warning, "a", True)

                query['jobid'] = jobid
                query['raw_query_seqfile'] = "query.raw.fa"
                query['BASEURL'] = g_params['BASEURL']

                # start the qd_fe if not, in the background
#                 cmd = [qd_fe_scriptfile]
                base_www_url = webcom.get_url_scheme(request) + request.META['HTTP_HOST']
                if webcom.IsFrontEndNode(base_www_url): #run the daemon only at the frontend
                    cmd = "nohup python %s &"%(qd_fe_scriptfile)
                    os.system(cmd)

                if query['nummodel'] < 0: #go to result page anyway
                    query['jobcounter'] = webcom.GetJobCounter(info)
                    return render(request, 'pred/thanks.html', query)
                else:
                    return get_results(request, jobid)

            else:
                query['jobcounter'] = webcom.GetJobCounter(info)
                return render(request, 'pred/badquery.html', query)

    # if a GET (or any other method) we'll create a blank form
    else:
        form = SubmissionForm()

    jobcounter = webcom.GetJobCounter(info)
    info['form'] = form
    info['jobcounter'] = jobcounter
    info['MAX_ALLOWD_NUMMODEL'] = g_params['MAX_ALLOWD_NUMMODEL']
    return render(request, 'pred/submit_seq.html', info)
#}}}
def IsDeepLearningFromLogFile(infile):#{{{
# determine whether deep learning is used based on the log file
    content = myfunc.ReadFile(infile)
    lines = content.split("\n")
    for line in lines:
        if line.find("-deep") != -1:
            strs = line.split()
            idx = strs.index("-deep")
            try:
                isDeepLearning = strs[idx+1]
                if isDeepLearning == "yes":
                    return True
                else:
                    return False
            except IndexError:
                return False
    return False
#}}}
def login(request):#{{{
    info = {}
    webcom.set_basic_config(request, info, g_params)
    info['jobcounter'] = webcom.GetJobCounter(info)
    return render(request, 'pred/login.html', info)
#}}}

def ValidateQuery(request, query):#{{{
    query['errinfo_br'] = ""
    query['errinfo_content'] = ""
    query['warninfo'] = ""
    query['filtered_seq'] = ""

    has_pasted_seq = False
    has_upload_seqfile = False
    if query['rawseq'].strip() != "":
        has_pasted_seq = True
    if query['seqfile'] != "":
        has_upload_seqfile = True

    has_pasted_model = False
    has_upload_modelfile = False
    if query['rawmodel'].strip() != "":
        has_pasted_model = True
    if query['modelfile'] != "":
        has_upload_modelfile = True


    if query['method_quality'] in ['lddt', 'tmscore', 'cad']:
        if not query['isDeepLearning']:
            query['errinfo_br'] += "Bad ProQ3 option!"
            query['errinfo_content'] = "Method for quality assessment '%s' "\
                    "can only be used for deep learning version of ProQ3. "\
                    "Please click checkbox 'Use deep learning' in the submission page "\
                    "and submit your job again."%(query['method_quality'])
            return False
        elif not query['isRepack']:
            query['errinfo_br'] += "Bad ProQ3 option!"
            query['errinfo_content'] = "Method for quality assessment '%s' "\
                    "can only be used for repacked models. "\
                    "Please click checkbox 'Perform side chain repacking' in the submission page "\
                    "and submit your job again."%(query['method_quality'])
            return False

    if has_pasted_model and has_upload_modelfile:
        query['errinfo_br'] += "Confused input!"
        query['errinfo_content'] = "You should input your model by either "\
                "paste the model in the text area or upload a file, but not both."
        return False
    elif not has_pasted_model and not has_upload_modelfile:
        query['errinfo_br'] += "No input!"
        query['errinfo_content'] = "You should input your query by either "\
                "paste the model in the text area or upload a file. "
        return False
    elif query['modelfile'] != "":
        try:
            fp = request.FILES['modelfile']
            fp.seek(0,2)
            filesize = fp.tell()
            if filesize > g_params['MAXSIZE_UPLOAD_MODELFILE_IN_BYTE']:
                query['errinfo_br'] += "Size of the uploaded model file exceeds the limit!"
                query['errinfo_content'] += "The file you uploaded exceeds "\
                        "the upper limit %g Mb. Please split your file and "\
                        "upload again."%(g_params['MAXSIZE_UPLOAD_MODELFILE_IN_MB'])
                return False

            fp.seek(0,0)
            content = fp.read()
        except KeyError:
            query['errinfo_br'] += ""
            query['errinfo_content'] += """
            Failed to read the uploaded file \"%s\"
            """%(query['modelfile'])
            return False
        query['rawmodel'] = content.decode('utf-8').replace('\r','')

    if has_pasted_seq and has_upload_seqfile:
        query['errinfo_br'] += "Confused input!"
        query['errinfo_content'] = "You should input your sequence by either "\
                "paste the sequence in the text area or upload a file, but not both."
        return False
    elif query['seqfile'] != "":
        try:
            fp = request.FILES['seqfile']
            fp.seek(0,2)
            filesize = fp.tell()
            if filesize > g_params['MAXSIZE_UPLOAD_SEQFILE_IN_BYTE']:
                query['errinfo_br'] += "Size of the uploaded sequence file exceeds the limit!"
                query['errinfo_content'] += "The file you uploaded exceeds "\
                        "the upper limit %g Mb. Please split your file and "\
                        "upload again."%(g_params['MAXSIZE_UPLOAD_SEQFILE_IN_MB'])
                return False

            fp.seek(0,0)
            content = fp.read()
        except KeyError:
            query['errinfo_br'] += ""
            query['errinfo_content'] += """
            Failed to read the uploaded file \"%s\"
            """%(query['seqfile'])
            return False
        query['rawseq'] = content.decode('utf-8')

    # parsing the raw model file by the MODEL, ENDMDL tag
    query['rawmodel'] = re.sub(r'[^\x00-\x7f]',r' ',query['rawmodel']) # remove non-ASCII characters
    query['rawmodel'] = re.sub(r'[\x0b]',r' ',query['rawmodel']) # filter invalid characters for XML
    query['rawmodel'] = re.sub(r'ATOM.*HT.*\n',r'',query['rawmodel']) # filter lines with HT residues

    modelList = myfunc.ReadPDBModelFromBuff(query['rawmodel'])

    nummodel = len(modelList)
    query['nummodel'] = nummodel
    query['modelList'] = modelList
    query['filtered_model' ] = ""

    if nummodel < 1:
        query['errinfo_br'] += "The number of models you input is 0!"
        query['errinfo_content'] += "Please check the format of the model you have input.";
        return False
    else:
        tmpli = []
        for ii in range(nummodel):
            tmpli.append("MODEL %d"%(ii+1))
            tmpli.append(modelList[ii])
            tmpli.append("ENDMDL")
        query['filtered_model'] = "\n".join(tmpli)

    query['filtered_seq'] = webcom.ValidateSeq(query['rawseq'], query, g_params)
    if query['rawseq'].strip() != "" and not query['isValidSeq']:
        return False
    else:
        return True
#}}}
def RunQuery(request, query):#{{{
    errmsg = []
    rstdir = tempfile.mkdtemp(prefix="%s/static/result/rst_"%(SITE_ROOT))
    os.chmod(rstdir, 0o755)
    jobid = os.path.basename(rstdir)
    query['jobid'] = jobid

# write files for the query
    jobinfofile = "%s/jobinfo"%(rstdir)
    rawseqfile = "%s/query.raw.fa"%(rstdir)
    seqfile_r = "%s/query.fa"%(rstdir)
    modelfile_r = "%s/query.pdb"%(rstdir)
    rawmodelfile = "%s/query.raw.pdb"%(rstdir)
    logfile = "%s/runjob.log"%(rstdir)

    query_para = {}
    query_para['name_software'] = "proq3"
    for item in ['targetlength', 'isRepack',
            'isDeepLearning','isKeepFiles','method_quality', 'isForceRun']:
        if item in query and query[item] != None:
            query_para[item] = query[item]
    query_para['isOutputPDB'] = True  #always output PDB file (with proq3 score written at the B-factor column)
    query_para['jobname'] = query['jobname']
    query_para['email'] = query['email']
    query_para['nummodel'] = query['nummodel']
    query_para['client_ip'] = query['client_ip']
    query_para['submit_date'] = query['date']
    query_para['method_submission'] = query['method_submission']
    query_parafile = "%s/query.para.txt"%(rstdir)

    jobinfo_str = "%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n"%(query['date'], jobid,
            query['client_ip'], query['nummodel'],
            len(query['rawseq']),query['jobname'], query['email'],
            query['method_submission'])
    errmsg.append(myfunc.WriteFile(jobinfo_str, jobinfofile, "w"))
    if query['rawseq'].strip() != "":
        errmsg.append(myfunc.WriteFile(query['rawseq'], rawseqfile, "w"))
    errmsg.append(myfunc.WriteFile(query['rawmodel'], rawmodelfile, "w"))
    if  query['filtered_seq'] != "":
        errmsg.append(myfunc.WriteFile(query['filtered_seq'], seqfile_r, "w"))
    errmsg.append(myfunc.WriteFile(query['filtered_model'], modelfile_r, "w"))
    errmsg.append(myfunc.WriteFile(json.dumps(query_para, sort_keys=True), query_parafile, "w"))
    base_www_url = webcom.get_url_scheme(request) + request.META['HTTP_HOST']
    query['base_www_url'] = base_www_url

#     if query['nummodel'] <= -1 : # do not submit any job to local queue
#         query['nummodel_this_user'] = query['nummodel']
#         SubmitQueryToLocalQueue(query, tmpdir, rstdir)

    forceruntagfile = "%s/forcerun"%(rstdir)
    if query['isForceRun']:
        myfunc.WriteFile("", forceruntagfile)
    return jobid
#}}}
def RunQuery_wsdl(rawseq, filtered_seq, seqinfo):#{{{
    errmsg = []
    tmpdir = tempfile.mkdtemp(prefix="%s/static/tmp/tmp_"%(SITE_ROOT))
    rstdir = tempfile.mkdtemp(prefix="%s/static/result/rst_"%(SITE_ROOT))
    os.chmod(tmpdir, 0o755)
    os.chmod(rstdir, 0o755)
    jobid = os.path.basename(rstdir)
    seqinfo['jobid'] = jobid
    numseq = seqinfo['numseq']

# write files for the query
    jobinfofile = "%s/jobinfo"%(rstdir)
    rawseqfile = "%s/query.raw.fa"%(rstdir)
    seqfile_t = "%s/query.fa"%(tmpdir)
    seqfile_r = "%s/query.fa"%(rstdir)
    warnfile = "%s/warn.txt"%(tmpdir)
    jobinfo_str = "%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n"%(seqinfo['date'], jobid,
            seqinfo['client_ip'], seqinfo['numseq'],
            len(rawseq),seqinfo['jobname'], seqinfo['email'],
            seqinfo['method_submission'])
    errmsg.append(myfunc.WriteFile(jobinfo_str, jobinfofile, "w"))
    errmsg.append(myfunc.WriteFile(rawseq, rawseqfile, "w"))
    errmsg.append(myfunc.WriteFile(filtered_seq, seqfile_t, "w"))
    errmsg.append(myfunc.WriteFile(filtered_seq, seqfile_r, "w"))

    # changed 2015-03-26, any jobs submitted via wsdl is hadndel
    return jobid
#}}}
def RunQuery_wsdl_local(rawseq, filtered_seq, seqinfo):#{{{
# submit the wsdl job to the local queue
    errmsg = []
    tmpdir = tempfile.mkdtemp(prefix="%s/static/tmp/tmp_"%(SITE_ROOT))
    rstdir = tempfile.mkdtemp(prefix="%s/static/result/rst_"%(SITE_ROOT))
    os.chmod(tmpdir, 0o755)
    os.chmod(rstdir, 0o755)
    jobid = os.path.basename(rstdir)
    seqinfo['jobid'] = jobid
    numseq = seqinfo['numseq']

# write files for the query
    jobinfofile = "%s/jobinfo"%(rstdir)
    rawseqfile = "%s/query.raw.fa"%(rstdir)
    seqfile_t = "%s/query.fa"%(tmpdir)
    seqfile_r = "%s/query.fa"%(rstdir)
    warnfile = "%s/warn.txt"%(tmpdir)
    jobinfo_str = "%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n"%(seqinfo['date'], jobid,
            seqinfo['client_ip'], seqinfo['numseq'],
            len(rawseq),seqinfo['jobname'], seqinfo['email'],
            seqinfo['method_submission'])
    errmsg.append(myfunc.WriteFile(jobinfo_str, jobinfofile, "w"))
    errmsg.append(myfunc.WriteFile(rawseq, rawseqfile, "w"))
    errmsg.append(myfunc.WriteFile(filtered_seq, seqfile_t, "w"))
    errmsg.append(myfunc.WriteFile(filtered_seq, seqfile_r, "w"))

    rtvalue = SubmitQueryToLocalQueue(seqinfo, tmpdir, rstdir)
    if rtvalue != 0:
        return ""
    else:
        return jobid
#}}}
def SubmitQueryToLocalQueue(query, tmpdir, rstdir):#{{{
    scriptfile = "%s/app/submit_job_to_queue.py"%(SITE_ROOT)
    rstdir = "%s/%s"%(path_result, query['jobid'])
    runjob_errfile = "%s/runjob.err"%(rstdir)
    debugfile = "%s/debug.log"%(rstdir) #this log only for debugging
    runjob_logfile = "%s/runjob.log"%(rstdir)
    failedtagfile = "%s/%s"%(rstdir, "runjob.failed")
    rmsg = ""

    cmd = [python_exec, scriptfile, "-nmodel", "%d"%query['nummodel'], "-nmodel-this-user",
            "%d"%query['nummodel_this_user'], "-jobid", query['jobid'],
            "-outpath", rstdir, "-datapath", tmpdir, "-baseurl",
            query['base_www_url'] ]
    if query['email'] != "":
        cmd += ["-email", query['email']]
    if query['client_ip'] != "":
        cmd += ["-host", query['client_ip']]
    if query['isForceRun']:
        cmd += ["-force"]

    (isSuccess, t_runtime) = webcom.RunCmd(cmd, runjob_logfile, runjob_errfile)

    if not isSuccess:
        webcom.WriteDateTimeTagFile(failedtagfile, runjob_logfile, runjob_errfile)
        return 1
    else:
        return 0
#}}}

def thanks(request):#{{{
    #print "request.POST at thanks:", request.POST
    return HttpResponse("Thanks")
#}}}

def get_queue(request):# {{{
    info = webcom.get_queue(request, g_params)
    return render(request, 'pred/queue.html', info)
# }}}
def get_running(request):# {{{
    info = webcom.get_running(request, g_params)
    return render(request, 'pred/running.html', info)
# }}}
def get_finished_job(request):# {{{
    info = webcom.get_finished_job(request, g_params)
    return render(request, 'pred/finished_job.html', info)
# }}}
def get_failed_job(request):# {{{
    info = webcom.get_failed_job(request, g_params)
    return render(request, 'pred/failed_job.html', info)
# }}}

def get_countjob_country(request):# {{{
    info = webcom.get_countjob_country(request, g_params)
    return render(request, 'pred/countjob_country.html', info)
# }}}
def get_help(request):# {{{
    info = webcom.get_help(request, g_params)
    return render(request, 'pred/help.html', info)
# }}}
def get_news(request):# {{{
    info = webcom.get_news(request, g_params)
    return render(request, 'pred/news.html', info)
# }}}
def help_wsdl_api(request):# {{{
    g_params['api_script_rtname'] =  "proq3_wsdl"
    info = webcom.help_wsdl_api(request, g_params)
    return render(request, 'pred/help_wsdl_api.html', info)
# }}}

def get_reference(request):#{{{
    info = {}
    webcom.set_basic_config(request, info, g_params)
    info['jobcounter'] = webcom.GetJobCounter(info)
    return render(request, 'pred/reference.html', info)
#}}}
def get_example(request):#{{{
    info = {}
    webcom.set_basic_config(request, info, g_params)
    info['jobcounter'] = webcom.GetJobCounter(info)
    return render(request, 'pred/example.html', info)
#}}}
def proq2(request):#{{{
    url_proq2 = "http://bioinfo.ifm.liu.se/ProQ2/index.php"
    return HttpResponseRedirect(url_proq2);
#}}}
def download(request):#{{{
    info = {}
    webcom.set_basic_config(request, info, g_params)
    info['jobcounter'] = webcom.GetJobCounter(info)
    return render(request, 'pred/download.html', info)
#}}}

def get_serverstatus(request):# {{{
    g_params['isShowLocalQueue'] = False
    info = webcom.get_serverstatus(request, g_params)
    return render(request, 'pred/serverstatus.html', info)
# }}}

def get_results(request, jobid="1"):#{{{
    resultdict = {}
    webcom.set_basic_config(request, resultdict, g_params)

    rstdir = "%s/%s"%(path_result, jobid)
    outpathname = jobid

    query_parafile = "%s/query.para.txt"%(rstdir)
    query_para = {}
    content = myfunc.ReadFile(query_parafile)
    if content != "":
        query_para = json.loads(content)

    resultfile = "%s/%s/%s/%s"%(rstdir, jobid, outpathname, "query.result.txt")
    tarball = "%s/%s.tar.gz"%(rstdir, outpathname)
    zipfile = "%s/%s.zip"%(rstdir, outpathname)
    starttagfile = "%s/%s"%(rstdir, "runjob.start")
    finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
    failtagfile = "%s/%s"%(rstdir, "runjob.failed")
    runjob_logfile = "%s/runjob.log"%(rstdir)
    errfile = "%s/%s"%(rstdir, "runjob.err")
    query_seqfile = "%s/%s"%(rstdir, "query.fa")
    raw_query_seqfile = "%s/%s"%(rstdir, "query.raw.fa")
    raw_query_modelfile = "%s/%s"%(rstdir, "query.raw.pdb")
    seqid_index_mapfile = "%s/%s/%s"%(rstdir,jobid, "seqid_index_map.txt")
    finished_model_file = "%s/%s/finished_models.txt"%(rstdir, jobid)

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

    modelfile = "%s/%s/model_0/query.pdb"%(rstdir, jobid)
    globalscorefile = "%s.%s.%s.global"%(modelfile, m_str, method_quality)
    if not os.path.exists(globalscorefile):
        globalscorefile = "%s.proq3.%s.global"%(modelfile, method_quality)
        if not os.path.exists(globalscorefile):
            globalscorefile = "%s.proq3.global"%(modelfile)

    dumped_resultfile = "%s/%s/%s"%(rstdir, jobid, "query.proq3.txt")
    statfile = "%s/%s/stat.txt"%(rstdir, jobid)
    method_submission = "web"

    jobinfofile = "%s/jobinfo"%(rstdir)
    jobinfo = myfunc.ReadFile(jobinfofile).strip()
    jobinfolist = jobinfo.split("\t")
    if len(jobinfolist) >= 8:
        submit_date_str = jobinfolist[0]
        nummodel = int(jobinfolist[3])
        jobname = jobinfolist[5]
        email = jobinfolist[6]
        method_submission = jobinfolist[7]
    else:
        submit_date_str = ""
        nummodel = 1
        jobname = ""
        email = ""
        method_submission = "web"

    isValidSubmitDate = True
    try:
        submit_date = webcom.datetime_str_to_time(submit_date_str)
    except ValueError:
        isValidSubmitDate = False
    current_time = datetime.now(timezone(TZ))

    resultdict['isResultFolderExist'] = True
    resultdict['errinfo'] = myfunc.ReadFile(errfile)

    status = ""
    queuetime = ""
    runtime = ""
    if not os.path.exists(rstdir):
        resultdict['isResultFolderExist'] = False
        resultdict['isFinished'] = False
        resultdict['isFailed'] = True
        resultdict['isStarted'] = False
    elif os.path.exists(failtagfile):
        resultdict['isFinished'] = False
        resultdict['isFailed'] = True
        resultdict['isStarted'] = True
        status = "Failed"
        start_date_str = myfunc.ReadFile(starttagfile).strip()
        isValidStartDate = True
        isValidFailedDate = True
        try:
            start_date = webcom.datetime_str_to_time(start_date_str)
        except ValueError:
            isValidStartDate = False
        failed_date_str = myfunc.ReadFile(failtagfile).strip()
        try:
            failed_date = webcom.datetime_str_to_time(failed_date_str)
        except ValueError:
            isValidFailedDate = False
        if isValidSubmitDate and isValidStartDate:
            queuetime = myfunc.date_diff(submit_date, start_date)
        if isValidStartDate and isValidFailedDate:
            runtime = myfunc.date_diff(start_date, failed_date)
    else:
        resultdict['isFailed'] = False
        if os.path.exists(finishtagfile):
            resultdict['isFinished'] = True
            resultdict['isStarted'] = True
            status = "Finished"
            isValidStartDate = True
            isValidFinishDate = True
            start_date_str = myfunc.ReadFile(starttagfile).strip()
            try:
                start_date = webcom.datetime_str_to_time(start_date_str)
            except ValueError:
                isValidStartDate = False
            finish_date_str = myfunc.ReadFile(finishtagfile).strip()
            try:
                finish_date = webcom.datetime_str_to_time(finish_date_str)
            except ValueError:
                isValidFinishDate = False
            if isValidSubmitDate and isValidStartDate:
                queuetime = myfunc.date_diff(submit_date, start_date)
            if isValidStartDate and isValidFinishDate:
                runtime = myfunc.date_diff(start_date, finish_date)
        else:
            resultdict['isFinished'] = False
            if os.path.exists(starttagfile):
                isValidStartDate = True
                start_date_str = myfunc.ReadFile(starttagfile).strip()
                try:
                    start_date = webcom.datetime_str_to_time(start_date_str)
                except ValueError:
                    isValidStartDate = False
                resultdict['isStarted'] = True
                status = "Running"
                if isValidSubmitDate and isValidStartDate:
                    queuetime = myfunc.date_diff(submit_date, start_date)
                if isValidStartDate:
                    runtime = myfunc.date_diff(start_date, current_time)
            else:
                resultdict['isStarted'] = False
                status = "Wait"
                if isValidSubmitDate:
                    queuetime = myfunc.date_diff(submit_date, current_time)

    color_status = webcom.SetColorStatus(status)

    file_seq_warning = "%s/%s/%s/%s"%(SITE_ROOT, "static/result", jobid, "query.warn.txt")
    seqwarninfo = ""
    if os.path.exists(file_seq_warning):
        seqwarninfo = myfunc.ReadFile(file_seq_warning)
        seqwarninfo = seqwarninfo.strip()

    resultdict['file_seq_warning'] = os.path.basename(file_seq_warning)
    resultdict['seqwarninfo'] = seqwarninfo
    resultdict['jobid'] = jobid
    resultdict['jobname'] = jobname
    resultdict['outpathname'] = os.path.basename(outpathname)
    resultdict['resultfile'] = os.path.basename(resultfile)
    resultdict['tarball'] = os.path.basename(tarball)
    resultdict['zipfile'] = os.path.basename(zipfile)
    resultdict['submit_date'] = submit_date_str
    resultdict['queuetime'] = queuetime
    resultdict['runtime'] = runtime
    resultdict['BASEURL'] = g_params['BASEURL']
    resultdict['status'] = status
    resultdict['color_status'] = color_status
    resultdict['nummodel'] = nummodel
    resultdict['method_quality'] = method_quality
    resultdict['query_seqfile'] = os.path.basename(query_seqfile)
    resultdict['m_str'] = m_str
    isHasTargetseq = False  # whether target sequence input in the submission page
    if os.path.exists(raw_query_seqfile):
        resultdict['raw_query_seqfile'] = os.path.basename(raw_query_seqfile)
        isHasTargetseq = True
    else:
        resultdict['raw_query_seqfile'] = ""

    resultdict['isHasTargetseq'] = isHasTargetseq
    resultdict['raw_query_modelfile'] = os.path.basename(raw_query_modelfile)
    base_www_url = webcom.get_url_scheme(request)  + request.META['HTTP_HOST']
    resultdict['url_result'] = "%s/pred/result/%s"%(base_www_url, jobid)

    sum_run_time = 0.0
    average_run_time = 120.0  # default average_run_time
    num_finished = 0
    cntnewrun = 0
    cntcached = 0
    # get seqid_index_map
    if os.path.exists(finished_model_file):
        # get headers for global scores from global score file
        if isHasTargetseq:
            resultdict['index_table_header'] = ["Model", "Length", "RunTime(s)"]
        else:
            resultdict['index_table_header'] = ["Model", "ModelSeq", "Length", "RunTime(s)"]

        proq3ScoreList = []
        if os.path.exists(globalscorefile):
            proq3ScoreList = webcom.GetProQ3ScoreListFromGlobalScoreFile(
                    globalscorefile)
        resultdict['index_table_header'] += proq3ScoreList

        index_table_content_list = []
        indexmap_content = myfunc.ReadFile(finished_model_file).split("\n")
        cnt = 0
        set_seqidx = set([])
        date_str = time.strftime(g_params['FORMAT_DATETIME'])
        for line in indexmap_content:
            strs = line.split("\t")
            if len(strs)>=3:
                subfolder = strs[0]
                if not subfolder in set_seqidx:
                    length_str = strs[1]
                    try:
                        runtime_in_sec_str = "%.1f"%(float(strs[2]))
                        # For single model jobs, the start time will be the
                        # same as finish time, so reset the runtime
                        if nummodel <= 1:
                            resultdict['runtime'] = myfunc.second_to_human(int(float(strs[2])+0.5))
                    except:
                        runtime_in_sec_str = ""


                    scoreList = []
                    for jj in range(3, len(strs)):
                        try:
                            score = "%.3f"%(float(strs[jj]))
                        except:
                            score = ""
                        scoreList.append(score)

                    if len(scoreList) == 0: #if the file finished_model_file is broken
                                            # read the score from
                                            # globalscorefile directly
                        t_modelfile = "%s/%s/%s/query.pdb"%(rstdir, jobid, subfolder)
                        t_globalscorefile = "%s.%s.%s.global"%(modelfile, m_str, method_quality)
                        (t_dict_globalscore, t_itemList) = webcom.ReadProQ3GlobalScore(t_globalscorefile)
                        for ii in range(len(t_itemList)):
                            scoreList.append(t_dict_globalscore[t_itemList[ii]])

                    model_idx = subfolder.lstrip('model_')
                    index_table_content_list.append([model_idx, length_str,
                        runtime_in_sec_str] + scoreList)
                    cnt += 1
                    set_seqidx.add(subfolder)
        if cntnewrun > 0:
            average_run_time = sum_run_time / cntnewrun

        resultdict['index_table_content_list'] = index_table_content_list
        resultdict['indexfiletype'] = "finishedfile"
        resultdict['num_finished'] = cnt
        num_finished = cnt
        resultdict['percent_finished'] = "%.1f"%(float(cnt)/nummodel*100)
    else:
        resultdict['index_table_header'] = []
        resultdict['index_table_content_list'] = []
        resultdict['indexfiletype'] = "finishedfile"
        resultdict['num_finished'] = 0
        resultdict['percent_finished'] = "%.1f"%(0.0)

    num_remain = nummodel - num_finished

    time_remain_in_sec = nummodel * 120 # set default value

    if os.path.exists(starttagfile):
        start_date_str = myfunc.ReadFile(starttagfile).strip()
        isValidStartDate = False
        try:
            start_date_epoch = webcom.datetime_str_to_epoch(start_date_str)
            isValidStartDate = True
        except:
            pass
        if isValidStartDate:
            time_now = time.time()
            runtime_total_in_sec = float(time_now) - float(start_date_epoch)
            cnt_torun = nummodel - cntcached #

            if cntnewrun <= 0:
                time_remain_in_sec = cnt_torun * 120
            else:
                time_remain_in_sec = int ( runtime_total_in_sec/float(cntnewrun)*cnt_torun+ 0.5)

    time_remain = myfunc.second_to_human(int(time_remain_in_sec+0.5))
    resultdict['time_remain'] = time_remain


    base_refresh_interval = 5 # seconds
    if nummodel <= 1:
        if method_submission == "web":
            resultdict['refresh_interval'] = base_refresh_interval
        else:
            resultdict['refresh_interval'] = base_refresh_interval
    else:
        #resultdict['refresh_interval'] = numseq * 2
        addtime = int(math.sqrt(max(0,min(num_remain, num_finished))))+1
        resultdict['refresh_interval'] = base_refresh_interval + addtime

    # get stat info
    if os.path.exists(statfile):#{{{
        content = myfunc.ReadFile(statfile)
        lines = content.split("\n")
        for line in lines:
            strs = line.split()
            if len(strs) >= 2:
                resultdict[strs[0]] = strs[1]
                percent =  "%.1f"%(int(strs[1])/float(numseq)*100)
                newkey = strs[0].replace('num_', 'per_')
                resultdict[newkey] = percent
#}}}
    resultdict['jobcounter'] = webcom.GetJobCounter(resultdict)
    return render(request, 'pred/get_results.html', resultdict)
#}}}
def get_results_eachseq(request, jobid="1", seqindex="1"):#{{{
    resultdict = {}
    webcom.set_basic_config(request, resultdict, g_params)

    rstdir = "%s/%s"%(path_result, jobid)
    outpathname = jobid

    jobinfofile = "%s/jobinfo"%(rstdir)
    jobinfo = myfunc.ReadFile(jobinfofile).strip()
    jobinfolist = jobinfo.split("\t")
    if len(jobinfolist) >= 8:
        submit_date_str = jobinfolist[0]
        numseq = int(jobinfolist[3])
        jobname = jobinfolist[5]
        email = jobinfolist[6]
        method_submission = jobinfolist[7]
    else:
        submit_date_str = ""
        numseq = 1
        jobname = ""
        email = ""
        method_submission = "web"

    status = ""

    resultdict['jobid'] = jobid
    resultdict['jobname'] = jobname
    resultdict['outpathname'] = os.path.basename(outpathname)
    resultdict['BASEURL'] = g_params['BASEURL']
    resultdict['status'] = status
    resultdict['numseq'] = numseq
    base_www_url = webcom.get_url_scheme(request)  + request.META['HTTP_HOST']

    resultfile = "%s/%s/%s/%s"%(rstdir, outpathname, seqindex, "query_topologies.txt")
    if os.path.exists(resultfile):
        resultdict['resultfile'] = os.path.basename(resultfile)
    else:
        resultdict['resultfile'] = ""

    resultdict['jobcounter'] = webcom.GetJobCounter(resultdict)
    return render(request, 'pred/get_results_eachseq.html', resultdict)
#}}}


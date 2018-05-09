#!/usr/bin/perl -w
#use lib '/usr/lib/perl5/5.6.1/';
use CGI qw(:standard); 
use CGI qw(:cgi-lib); 
use CGI qw(:upload); 

use CGI::Carp 'fatalsToBrowser';#debug nanjiang
use POSIX qw(strftime);

use Fcntl ':flock';
use Cwd 'abs_path'; 
use File::Basename;
use File::Spec;
use File::Temp;
use JSON;


my $cgi = new CGI;

my $PROGNAME = basename($0);

my $rundir = dirname(abs_path($0));
my $basedir = abs_path("$rundir/../pred");
my $path_result = "$basedir/static/result";
my $path_tmp = "$basedir/static/tmp";
my $submitjoblogfile = "$basedir/static/log/submitted_seq.log";

my $hostname_of_the_computer = `hostname` ;
my $date = localtime();
my $output_str = "";
my $myemail="nanjiang.shu\@scilifelab.se";
my $vip_emailfile = "$basedir/config/vip_email.txt";

print $cgi->header();
print $cgi->start_html(-title => "ProQ3 Submission",
    -author => "nanjiang.shu\@scilifelab.se",
    -meta   => {'keywords'=>''});

if(!$cgi->param()) {
    print "<pre>\n";
    print "usage: curl submitjob.cgi -F button=1 -F structure=filename -F email=email -F targetseq=seq -F deep=yes_or_no -F method_quality=method_quality\n\n";
    print "Examples:\n";
    print "       curl submitjob.cgi -F button=1 -F structure=model.pdb -F email=someone\@domain.com -F targetseq=AATT -F deep=yes -F method_quality=lddt \n";
    print "</pre>\n";
    print $cgi->end_html();
    exit (1);
} else {
    my $targetseq = "";
    my $name = "";
    my $email = "";
    my $f_structure = "";
    my $method_quality = "";
    my $host = "";
    my $isDeepLearning = JSON::true;
    my $yes_or_no_deeplearning = "yes";

    $targetseq = $cgi->param('targetseq');
    $targetseq=~s/\n//g;
    $targetseq=~s/\s+//g;
    $name = $cgi->param('name');      # Title for CAMEO
    $email = $cgi->param('email');    # email of the submitter
    $host = $cgi->param('host');      # IP address of the submitter
    $method_quality = $cgi->param('method_quality');  # method_quality for PROQ3D
    $f_structure = $cgi->param('structure');    # structure info in PDB format
    $yes_or_no_deeplearning = $cgi->param('deep');    # structure info in PDB format

    my $f_name = basename($f_structure);

    if(length($f_structure)<1)
    {
        print 'Error: f_structure is not provided. Exit!';
        exit;
    }

    if ($method_quality eq ""){
        $method_quality = "sscore";
    }

    if ($yes_or_no_deeplearning  eq "yes" or $yes_or_no_deeplearning eq ""){
        $isDeepLearning = JSON::true;
    }else{
        $isDeepLearning = JSON::false;
    }
    my $isCAMEOtarget = 0;
    if ($email =~ /proteinmodelportal\.org/){
        $isCAMEOtarget = 1;
    }

    my $isVIP = 0;
    if ($email =~ /nanjiang\.shu\@scilifelab\.se/){
        $isVIP = 1;
    }

    my $structure = "";
    (my $tmpfh, my $tmpfile) = File::Temp::tempfile("$path_tmp/tmp_XXXXXX", SUFFIX=>".pdb");
    `chmod 644 $tmpfile`;
    my $fh = $cgi->upload('structure');
    binmode $tmpfh;
    while(<$fh>) {
        print $tmpfh $_;
        $structure .= $_;
    }

    close($fh);
    close($tmpfh);

    if ($isCAMEOtarget or $isVIP){
        CreateJob(JSON::false, "sscore", $targetseq, $structure, $name, $email, $host, $isCAMEOtarget, $isVIP);
        CreateJob(JSON::true, "sscore", $targetseq, $structure, $name, $email, $host, $isCAMEOtarget, $isVIP);
        CreateJob(JSON::true, "lddt", $targetseq, $structure, $name, $email, $host, $isCAMEOtarget, $isVIP);
    } else {
        CreateJob($isDeepLearning, $method_quality, $targetseq, $structure, $name, $email, $host, $isCAMEOtarget, $isVIP);
    }

    print $cgi->end_html();
}

sub WriteFile{#{{{ content outfile Write File
    my $content = shift;
    my $outfile = shift;
    open(OUT,">$outfile");
    print OUT $content;
    close(OUT);
}#}}}
sub CreateJob{#{{{
    my $isDeepLearning = shift;
    my $method_quality = shift;
    my $targetseq = shift;
    my $structure = shift;
    my $name = shift;
    my $email = shift;
    my $host = shift;
    my $isCAMEOtarget = shift;
    my $isVIP = shift;
    # create the job folder 
    my $rstdir = File::Temp::tempdir("$path_result/rst_XXXXXX", CLEANUP=>0);
    `chmod 755 $rstdir`;
    my $jobid = basename($rstdir);
    my $client_ip = $ENV{'REMOTE_ADDR'};
    my $method_submission = "cgi";

    my $description = "query";
    if ($name ne ""){
        $description = $name;
    }

    my $jobinfofile = "$rstdir/jobinfo";
    my $rawseqfile = "$rstdir/query.raw.fa";
    my $seqfile = "$rstdir/query.fa";
    my $modelfile = "$rstdir/query.pdb";
    my $rawmodelfile = "$rstdir/query.raw.pdb";
    my $query_parafile = "$rstdir/query.para.txt";

    my $nummodel = 1;
    my $length_rawmodel = length($structure);

    if ($isCAMEOtarget){
        WriteFile("CAMEO", "$rstdir/submitter.txt");
    }
    if ($isVIP){
        WriteFile("VIP", "$rstdir/submitter.txt");
    }


    # write data of submitted query to rstdir
    if ($targetseq ne ""){
        WriteFile(">$description\n$targetseq\n", $rawseqfile);
        WriteFile(">$description\n$targetseq\n", $seqfile);
    }
    if ($structure ne ""){
        WriteFile($structure, $rawmodelfile);
        my $cnt = `cat $rawmodelfile | grep ENDMDL | wc -l`;
        if ($cnt > 0){
            $nummodel = $cnt;
            WriteFile($structure, $modelfile);
        }else{
            my $n_structure = "MODEL 1\n$structure\nENDMDL\n";
            WriteFile($n_structure, $modelfile);
        }
    }
    my $submit_date = strftime "%Y-%m-%d %H:%M:%S", localtime;
    my $jobinfo = "$submit_date\t$jobid\t$client_ip\t$nummodel\t$length_rawmodel\t$name\t$email\t$method_submission";
    WriteFile($jobinfo, $jobinfofile);


    my $loginfo = "$submit_date\t$jobid\t$client_ip\t$nummodel\t$length_rawmodel\t$name\t$email\t$method_submission";

    open(OUT, ">>$submitjoblogfile") || die;
    flock(OUT, 2) || die;
    print OUT "$loginfo\n";
    close(OUT);

    my %query_para = (
        'isDeepLearning' => $isDeepLearning,
        'isKeepFiles' => JSON::true,
        'isRepack' => JSON::true,
        'isForceRun' => JSON::false,
        'name_software' => 'proq3', 
        'method_quality' => $method_quality,
        'isOutputPDB' => JSON::true,
        'jobname' => $name,
        'email' => $email,
        'nummodel' => $nummodel,
        'client_ip' => $client_ip,
        'method_submission' => $method_submission,
        'submit_date' => $submit_date,
    );
    my $json_para_str = encode_json \%query_para;

    WriteFile($json_para_str, $query_parafile);

    print "Your query (isDeepLearning: $isDeepLearning, quality: $method_quality) has been submitted successfully with jobid = $jobid\n";
    WriteFile($submit_date, "$path_result/static/log/lastsubmission.txt");
}
#}}}
sub DisplayForm {#{{{
    print <<"HTML";
<html>
<head>
<title>Upload Form</title>
<body>
<h1>Upload Form</h1>
<form method="post" action="$PROGNAME" enctype="multipart/form-data">
<center>
Enter a file to upload: <input type="file" name="structure"><br>
<input type="submit" name="button" value="Upload">
</center>
</form>

HTML
}#}}}

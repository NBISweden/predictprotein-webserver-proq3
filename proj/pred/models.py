from django.db import models
from django import forms

from django.core.validators import MinLengthValidator, MaxLengthValidator 

# Create your models here.

class Query(models.Model):
    raw_seq = models.CharField(max_length=20000)
    seqname = models.CharField(max_length=100)
    submit_date = models.DateTimeField('date submitted')

class SubmissionForm_bak(forms.Form):#{{{
    """
    Defining the form to submit queries
    """
    rawseq = forms.CharField(label='', max_length=100000,
            widget=forms.Textarea(attrs={'cols': 62, 'rows': 10}),
            required=False)
    seqfile = forms.FileField(label="Alternatively, upload a text file in FASTA format upto 150 KB", required=False)
    jobname = forms.CharField(label='Job name (optional)', max_length=100, required=False)
    email = forms.CharField(label='Email (optional)', max_length=100, required=False)
#}}}

class SubmissionForm(forms.Form):
    """
    Defining the form to submit queries
    """
    rawmodel = forms.CharField(label='Paste your model in PDB format (up to 10 MB)\n', max_length=130000000,
            widget=forms.Textarea(attrs={'cols': 70, 'rows': 10, 'wrap': 'off'}),
            required=False)
    modelfile = forms.FileField(label="Or, upload the model file (up to 10 MB)", required=False)
    rawseq = forms.CharField(label='Paste the amino acid sequence of your model in FASTA format (recommended, up to 10 KB)\n', max_length=100000,
        widget=forms.Textarea(attrs={'cols': 70, 'rows': 4}),
            required=False)
    seqfile = forms.FileField(label="Or, upload your sequence file (up to 10 KB)", required=False)
    targetlength = forms.IntegerField(label='Length of target (optional)', min_value=1, required=False)
    jobname = forms.CharField(label='Job name (optional)', max_length=100, required=False)
    email = forms.EmailField(label='Email (recommended)', max_length=100, required=False)
    repacking = forms.BooleanField(label='Perform side chain repacking', initial=True, required=False)
    method_quality_choices = (('1', 'sscore'), ('2', 'cad'),('3', 'tmscore'),('4', 'lddt') )
    method_quality = forms.TypedChoiceField(label='Method for quality measurement', choices=method_quality_choices, initial='1', required=False)
    deep = forms.BooleanField(label='Using deep learning', initial=False, required=False)
    #keepfile = forms.BooleanField(label='Keep repacked models and SVM output', required=False)
    forcerun = forms.BooleanField(label='Force run (do not use cached profiles)', initial=False, required=False)


class FieldContainer(models.Model):
# This class is modified from the Spyne example written by BJ Cardon
# Copyright BJ Cardon <bj dot car dot don at gmail dot com>,
# All rights reserved.
    char_field = models.CharField(max_length=32, default='test')
    char_field_nullable = models.CharField(max_length=32, null=True)
    slug_field = models.SlugField(max_length=32, unique=True)
    text_field = models.TextField(default='text_field')
    email_field = models.EmailField()
    boolean_field = models.BooleanField(default=True)
    integer_field = models.IntegerField(default=1)
    positive_integer_field = models.PositiveIntegerField(default=1)
    float_field = models.FloatField(default=1)
    decimal_field = models.DecimalField(max_digits=10, decimal_places=4,
                                        default=1)
    time_field = models.TimeField(auto_now_add=True)
    date_field = models.DateField(auto_now_add=True)
    datetime_field = models.DateTimeField(auto_now_add=True)

    foreign_key = models.ForeignKey('self', null=True,
                                    related_name='related_containers')
    one_to_one_field = models.OneToOneField('self', null=True)

    custom_foreign_key = models.ForeignKey(
        'RelatedFieldContainer', null=True,
        related_name='related_fieldcontainers')
    custom_one_to_one_field = models.OneToOneField('RelatedFieldContainer',
                                                   null=True)

    url_field = models.URLField(default='http://example.com')
    file_field = models.FileField(upload_to='test_file', null=True)
    excluded_field = models.CharField(max_length=32, default='excluded')
    blank_field = models.CharField(max_length=32, blank=True)
    length_validators_field = models.CharField(
        max_length=32, null=True, validators=[MinLengthValidator(3),
                                              MaxLengthValidator(10)])


class RelatedFieldContainer(models.Model):
# This class is modified from the Spyne example written by BJ Cardon
# Copyright BJ Cardon <bj dot car dot don at gmail dot com>,
# All rights reserved.
    id = models.CharField(max_length=30, primary_key=True)



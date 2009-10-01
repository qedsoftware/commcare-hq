from xformmanager.storageutility import * 
from xformmanager.xformdef import FormDef
from xformmanager.models import MetaDataValidationError
import uuid
import subprocess
from subprocess import PIPE

class XFormManager(object):
    """ This class makes the process of handling formdefs (our 
    representation of schemas) and formdefmodels (db interaction layer),
    completely transparent to the programmers
    """
    def __init__(self):
        self.su  = StorageUtility()

    def remove_schema(self, id, remove_submissions=False):
        self.su.remove_schema(id, remove_submissions)    

    def remove_data(self, formdef_id, id, remove_submission=False):
        self.su.remove_instance_matching_schema(formdef_id, id, remove_submission)
        
    def save_schema_POST_to_file(self, stream, file_name):
        """ save POST to file """
        try:
            type = file_name.rsplit('.',1)[1]
        except IndexError:
            # POSTed file has no extension
            type = "xform"
        filename = self._save_schema_stream_to_file(stream, type)
        return filename

    def save_form_data(self, xml_file_name, attachment):
        """ return True on success and False on fail """
        return self.su.save_form_data(xml_file_name, attachment)
    
    def validate_schema(self, file_name):
        """ validate schema 
        Returns a tuple (is_valid, error)
        is_valid - True if valid, False if not
        error - Relevant validation error
        """
        #process xsd file to FormDef object
        fout = open(file_name, 'r')
        formdef = FormDef(fout)
        fout.close()
        
        try:
            formdef.validate()
        except Exception, e:
            return False, e
        return True, None

    def create_schema_from_file(self, new_file_name):
        """ process schema """
        #process xsd file to FormDef object
        fout = open(new_file_name, 'r')
        formdef = FormDef(fout)
        fout.close()
        formdefmodel = self.su.add_schema (formdef)
        formdefmodel.xsd_file_location = new_file_name
        formdefmodel.save()
        return formdefmodel

    def add_schema_manually(self, schema, type):
        """ manually register a schema """
        file_name = self._save_schema_string_to_file(schema, type)
        return self.create_schema_from_file(file_name)

    def add_schema(self, file_name, input_stream):
        """ we keep this api open for the unit tests """
        file_name = self.save_schema_POST_to_file(input_stream, file_name)
        return self.create_schema_from_file(file_name)
    
    def _save_schema_string_to_file(self, string, type ):
        transaction_str = str(uuid.uuid1())
        new_file_name = self._xsd_file_name(transaction_str)
        if type.lower() == "xsd":
            fout = open(new_file_name, 'w')
            fout.write( string )
            fout.close()
        else:
            #user has uploaded an xhtml/xform file
            # save the raw xform
            xform_filename = new_file_name + str(".xform")
            xform_handle = open(xform_filename, 'w')
            xform_handle.write( string )
            xform_handle.close()
            fin = open(xform_filename, 'r')
            schema,err,has_error = form_translate( fin.read() )
            fin.close()
            if has_error:
                raise IOError, "Could not convert xform to schema." + \
                               " Please verify that this is a valid xform file."
            fout = open(new_file_name, 'w')
            fout.write( schema )
            fout.close()
        return new_file_name

    def _save_schema_stream_to_file(self, stream, type):
        return self._save_schema_string_to_file(stream.read(), type)

    def _xsd_file_name(self, name):
        return os.path.join(settings.RAPIDSMS_APPS['xformmanager']['xsd_repository_path'], 
                            str(name) + '-xsd.xml')

class FormDefError(SyntaxError):
    """ Generic error for XFormManager.Manager """
    pass

def form_translate(input_stream):
    '''Translates an xform into an xsd file'''
    logging.debug ("XFORMMANAGER.VIEWS: begin subprocess - java -jar form_translate.jar schema < input file > ")
    p = subprocess.Popen(["java","-jar",os.path.join(settings.RAPIDSMS_APPS['xformmanager']['xform_translate_path'],"form_translate.jar"),'schema'], shell=False, stdout=subprocess.PIPE,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    logging.debug ("XFORMMANAGER.VIEWS: begin communicate with subprocess")
    
    p.stdin.write(input_stream)
    p.stdin.flush()
    p.stdin.close()
    
    output = p.stdout.read()    
    error = p.stderr.read()
    
    # error has data even when things go perfectly, so return both
    # the full stream and a boolean indicating whether there was an
    # error.  This should be fixed in a cleaner way.
    has_error = "exception" in error.lower() 
    logging.debug ("XFORMMANAGER.VIEWS: finish communicate with subprocess")
    return (output,error, has_error)

def get_formdef(target_namespace, version=None):
    """ given a form and version get me that formdef
    If formdef could not be found/parsed, returns None
    """
    try:
        formdefmodel = FormDefModel.objects.get(target_namespace=target_namespace,
                                                version=version)
    except FormDefModel.DoesNotExist:
        return None
    if formdefmodel.xsd_file_location is None:
        raise IOError("Schema for form %s could not be found on the file system." % \
                      target_namespace)
    formdef = FormDef.from_file(formdefmodel.xsd_file_location)
    return formdef

def is_schema_registered(self, target_namespace, version=None):
    return is_schema_registered(target_namespace, version)

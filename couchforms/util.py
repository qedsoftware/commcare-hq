from __future__ import absolute_import
import hashlib
import datetime
import logging

from StringIO import StringIO
from django.test.client import Client

from couchdbkit import ResourceConflict, ResourceNotFound, resource
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseServerError,
)

import couchforms
from couchforms.const import MAGIC_PROPERTY, MULTIPART_FILENAME_ERROR
from couchforms.exceptions import DuplicateError
from dimagi.utils.mixins import UnicodeMixIn
from couchforms.models import (
    DefaultAuthContext,
    SubmissionErrorLog,
    XFormDeprecated,
    XFormDuplicate,
    XFormError,
    XFormInstance,
    doc_types,
)
from couchforms.signals import (
    ReceiverResult,
    submission_error_received,
    successful_form_received,
)
from dimagi.utils.couch import uid
from couchforms import xml
from couchforms.xml import ResponseNature
import xml2json


class SubmissionError(Exception, UnicodeMixIn):
    """
    When something especially bad goes wrong during a submission, this
    exception gets raised.
    """

    def __init__(self, error_log, *args, **kwargs):
        super(SubmissionError, self).__init__(*args, **kwargs)
        self.error_log = error_log
    
    def __str__(self):
        return str(self.error_log)


def _extract_meta_instance_id(form):
    """Takes form json (as returned by xml2json)"""
    if form.get('Meta'):
        # bhoma, 0.9 commcare
        meta = form['Meta']
    elif form.get('meta'):
        # commcare 1.0
        meta = form['meta']
    else:
        return None

    if meta.get('uid'):
        # bhoma
        return meta['uid']
    elif meta.get('instanceID'):
        # commcare 0.9, commcare 1.0
        return meta['instanceID']
    else:
        return None


def convert_xform_to_json(xml_string):
    """
    takes xform payload as xml_string and returns the equivalent json
    i.e. the json that will show up as xform.form

    """

    try:
        name, json_form = xml2json.xml2json(xml_string)
    except xml2json.XMLSyntaxError as e:
        raise couchforms.XMLSyntaxError(u'Invalid XML: %s' % e)
    json_form['#type'] = name
    return json_form


def create_xform_from_xml(xml_string, _id=None, process=None):
    """
    create and save an XFormInstance from an xform payload (xml_string)
    optionally set the doc _id to a predefined value (_id)
    return doc _id of the created doc

    `process` is transformation to apply to the form right before saving
    This is to avoid having to save multiple times

    If xml_string is bad xml
      - raise couchforms.XMLSyntaxError
      - do not save form

    """
    json_form = convert_xform_to_json(xml_string)

    _id = _id or _extract_meta_instance_id(json_form)

    kwargs = dict(
        _attachments=resource.encode_attachments({
            "form.xml": {
                "content_type": "text/xml",
                "data": xml_string,
            },
        }),
        form=json_form,
        xmlns=json_form.get('@xmlns'),
        received_on=datetime.datetime.utcnow(),
        **{'#export_tag': 'xmlns'}
    )
    if _id:
        kwargs['_id'] = _id

    xform = XFormInstance(**kwargs)

    try:
        if process:
            process(xform)
    except Exception:
        # if there's any problem with process just save what we had before
        # rather than whatever intermediate state `process` left it in
        xform = XFormInstance(**kwargs)
        raise
    finally:
        try:
            xform.save(encode_attachments=False)
        except ResourceConflict:
            raise DuplicateError()

    return xform.get_id


def post_xform_to_couch(instance, attachments=None, process=None):
    """
    Save a new xform to couchdb
    Returns the newly created document from couchdb,
    or raises an exception if anything goes wrong.

    attachments is a dictionary of the request.FILES that are not the xform;
    key is parameter name, value is django MemoryFile object stream
    """
    attachments = attachments or {}

    try:
        doc_id = create_xform_from_xml(instance, process=process)
    except couchforms.XMLSyntaxError as e:
        doc = _log_hard_failure(instance, attachments, e)
        raise SubmissionError(doc)
    except DuplicateError:
        return _handle_id_conflict(instance, attachments, process=process)

    try:
        xform = XFormInstance.get(doc_id)
        for key, value in attachments.items():
            xform.put_attachment(
                value,
                name=key,
                content_type=value.content_type,
                content_length=value.size
            )
        return xform
    except Exception, e:
        logging.exception("Problem with form %s" % doc_id)
        # "rollback" by changing the doc_type to XFormError
        bad = XFormError.get(doc_id)
        bad.problem = unicode(e)
        bad.save()
        return bad


def _has_errors(response, errors):
    return errors or "error" in response


def _extract_id_from_raw_xml(xml):
    # the code this is replacing didn't deal with the error either
    # presumably because it's already been run once by the time it gets here
    _, json_form = xml2json.xml2json(xml)
    return _extract_meta_instance_id(json_form) or ''


def _handle_id_conflict(instance, attachments, process):
    """
    For id conflicts, we check if the files contain exactly the same content,
    If they do, we just log this as a dupe. If they don't, we deprecate the 
    previous form and overwrite it with the new form's contents.
    """
    
    conflict_id = _extract_id_from_raw_xml(instance)
    
    # get old document
    existing_doc = XFormInstance.get(conflict_id)

    # compare md5s
    existing_md5 = existing_doc.xml_md5()
    new_md5 = hashlib.md5(instance).hexdigest()

    # if not same:
    # Deprecate old form (including changing ID)
    # to deprecate, copy new instance into a XFormDeprecated
    if existing_md5 != new_md5:
        doc_copy = XFormInstance.get_db().copy_doc(conflict_id)
        # get the doc back to avoid any potential bigcouch race conditions.
        # r=3 implied by class
        xfd = XFormDeprecated.get(doc_copy['id'])
        xfd.orig_id = conflict_id
        xfd.doc_type = XFormDeprecated.__name__
        xfd.save()

        # after that delete the original document and resubmit.
        XFormInstance.get_db().delete_doc(conflict_id)
        return post_xform_to_couch(instance, attachments=attachments,
                                   process=process)
    else:
        # follow standard dupe handling
        new_doc_id = uid.new()
        new_form_id = create_xform_from_xml(instance, _id=new_doc_id,
                                            process=process)

        # create duplicate doc
        # get and save the duplicate to ensure the doc types are set correctly
        # so that it doesn't show up in our reports
        dupe = XFormDuplicate.get(new_form_id)
        dupe.problem = "Form is a duplicate of another! (%s)" % conflict_id
        dupe.save()
        return dupe


def _log_hard_failure(instance, attachments, error):
    """
    Handle's a hard failure from posting a form to couch. 
    
    Currently, it will save the raw payload to couch in a hard-failure doc
    and return that doc.
    """
    try:
        message = unicode(error)
    except UnicodeDecodeError:
        message = unicode(str(error), encoding='utf-8')

    return SubmissionErrorLog.from_instance(instance, message)


def scrub_meta(xform):
    """
    Cleans up old format metadata to our current standard.

    Does NOT save the doc, but returns whether the doc needs to be saved.
    """
    property_map = {'TimeStart': 'timeStart',
                    'TimeEnd': 'timeEnd',
                    'chw_id': 'userID',
                    'DeviceID': 'deviceID',
                    'uid': 'instanceID'}

    if not hasattr(xform, 'form'):
        return

    # hack to make sure uppercase meta still ends up in the right place
    found_old = False
    if 'Meta' in xform.form:
        xform.form['meta'] = xform.form['Meta']
        del xform.form['Meta']
        found_old = True
    if 'meta' in xform.form:
        meta_block = xform.form['meta']
        # scrub values from 0.9 to 1.0
        if isinstance(meta_block, list):
            if isinstance(meta_block[0], dict):
                # if it's a list of dictionaries, arbitrarily pick the first one
                # this is a pretty serious error, but it's also recoverable
                xform.form['meta'] = meta_block = meta_block[0]
                logging.error((
                    'form %s contains multiple meta blocks. '
                    'this is not correct but we picked one abitrarily'
                ) % xform.get_id)
            else:
                # if it's a list of something other than dictionaries.
                # don't bother scrubbing.
                logging.error('form %s contains a poorly structured meta block.'
                              'this might cause data display problems.')
        if isinstance(meta_block, dict):
            for key in meta_block:
                if key in property_map and property_map[key] not in meta_block:
                    meta_block[property_map[key]] = meta_block[key]
                    del meta_block[key]
                    found_old = True

    return found_old


class SubmissionPost(object):

    def __init__(self, instance=None, attachments=None,
                 auth_context=None, domain=None, app_id=None, path=None,
                 location=None, submit_ip=None, openrosa_headers=None,
                 last_sync_token=None, received_on=None, date_header=None):
        assert domain, domain
        assert instance, instance
        assert not isinstance(instance, HttpRequest), instance
        # get_location has good default
        self.domain = domain
        self.app_id = app_id
        self.location = location or couchforms.get_location()
        self.received_on = received_on
        self.date_header = date_header
        self.submit_ip = submit_ip
        self.last_sync_token = last_sync_token
        self.openrosa_headers = openrosa_headers
        self.instance = instance
        self.attachments = attachments or {}
        self.auth_context = auth_context or DefaultAuthContext()
        self.path = path

    def _attach_shared_props(self, doc):
        # attaches shared properties of the request to the document.
        # used on forms and errors
        doc['auth_context'] = self.auth_context.to_json()
        doc['submit_ip'] = self.submit_ip
        doc['path'] = self.path

        doc['openrosa_headers'] = self.openrosa_headers

        doc['last_sync_token'] = self.last_sync_token

        if self.received_on:
            doc.received_on = self.received_on

        if self.date_header:
            doc['date_header'] = self.date_header

        doc['domain'] = self.domain
        doc['app_id'] = self.app_id
        doc['#export_tag'] = ["domain", "xmlns"]

        return doc

    def get_response(self):
        if not self.auth_context.is_valid():
            return self.get_failed_auth_response()

        if self.instance is MULTIPART_FILENAME_ERROR:
            return HttpResponseBadRequest((
                'If you use multipart/form-data, '
                'please name your file %s.\n'
                'You may also do a normal (non-multipart) post '
                'with the xml submission as the request body instead.'
            ) % MAGIC_PROPERTY)

        def process(xform):
            self._attach_shared_props(xform)
            scrub_meta(xform)

        try:
            doc = post_xform_to_couch(self.instance,
                                      attachments=self.attachments,
                                      process=process)
            return self.get_success_response(doc)
        except SubmissionError as e:
            logging.exception(
                u"Problem receiving submission to %s. %s" % (
                    self.path,
                    unicode(e),
                )
            )
            return self.get_error_response(e.error_log)

    def get_failed_auth_response(self):
        return HttpResponseForbidden('Bad auth')

    def success_actions_and_respond(self, doc):
        feedback = successful_form_received.send_robust(sender='receiver', xform=doc)
        responses = []
        errors = []
        for func, resp in feedback:
            if resp and isinstance(resp, Exception):
                error_message = unicode(resp)
                # hack to log exception type (no valuable stacktrace though)
                try:
                    raise resp
                except Exception:
                    logging.exception((
                        u"Receiver app: problem sending "
                        u"post-save signal %s for xform %s: %s"
                    ) % (func, doc._id, error_message))
                errors.append(error_message)
            elif resp and isinstance(resp, ReceiverResult):
                responses.append(resp)

        if errors:
            # in the event of errors, respond with the errors, and mark the problem
            doc.problem = ", ".join(errors)
            doc.save()
            response = HttpResponse(
                xml.get_simple_response_xml(
                    message=doc.problem,
                    nature=ResponseNature.SUBMIT_ERROR,
                ),
                status=201,
            )
        elif responses:
            # use the response with the highest priority if we got any
            responses.sort()
            response = HttpResponse(responses[-1].response, status=201)
        else:
            # default to something generic
            response = HttpResponse(
                xml.get_simple_response_xml("Thanks for submitting!",
                                            ResponseNature.SUBMIT_SUCCESS),
                status=201,
            )
        return response

    def fail_actions_and_respond(self, doc):
        return HttpResponse(
            xml.get_simple_response_xml(
                message=doc.problem,
                nature=ResponseNature.SUBMIT_ERROR,
            ),
            status=201,
        )

    def get_success_response(self, instance):
        if instance.doc_type == "XFormInstance":
            response = self.success_actions_and_respond(instance)
        else:
            response = self.fail_actions_and_respond(instance)

        # this hack is required for ODK
        response["Location"] = self.location

        # this is a magic thing that we add
        response['X-CommCareHQ-FormID'] = instance.get_id
        return response

    def get_error_response(self, error_log):
        error_doc = SubmissionErrorLog.get(error_log.get_id)
        self._attach_shared_props(error_doc)
        submission_error_received.send(sender="receiver", xform=error_doc)
        error_doc.save()
        return HttpResponseServerError(
            xml.get_simple_response_xml(
                message="The sever got itself into big trouble! Details: %s" % error_log.problem,
                nature=ResponseNature.SUBMIT_ERROR))


def fetch_and_wrap_form(doc_id):
    # This logic is independent of couchforms; when it moves elsewhere,
    # please use the most appropriate alternative to get a DB handle.

    db = XFormInstance.get_db()
    doc = db.get(doc_id)
    if doc['doc_type'] in doc_types():
        return doc_types()[doc['doc_type']].wrap(doc)
    raise ResourceNotFound(doc_id)


def spoof_submission(submit_url, body, name="form.xml", hqsubmission=True,
                     headers=None):
    if headers is None:
        headers = {}
    client = Client()
    f = StringIO(body.encode('utf-8'))
    f.name = name
    response = client.post(submit_url, {
        'xml_submission_file': f,
    }, **headers)
    if hqsubmission:
        xform_id = response['X-CommCareHQ-FormID']
        xform = XFormInstance.get(xform_id)
        xform['doc_type'] = "HQSubmission"
        xform.save()
    return response


import pandas as pd
import numpy as np
import json
import os
from datetime import datetime
from datetime import timezone
from parser import Parser

class Repertoire(Parser):
    
    def __init__(self, verbose, repository_tag, repository_chunk, airr_map, repository):
        Parser.__init__(self, verbose, repository_tag, repository_chunk, airr_map, repository)
    
    # Utility function to check to see if a given value is a valid type for a specific
    # AIRR field.  If doing strict AIRR checks, if the field is not an AIRR field then
    # it returns FALSE. If not doing strict AIRR checks, then it doesn't do any checks
    # against the the field if it isn't an AIRR field (it returns TRUE). 
    def validAIRRFieldType(self, key, value, strict):
        field_type = self.getAIRRMap().getMapping(key, self.getAIRRTag(),
                               "airr_type", self.getAIRRMap().getRepertoireClass())
        field_nullable = self.getAIRRMap().getMapping(key, self.getAIRRTag(),
                               "airr_nullable", self.getAIRRMap().getRepertoireClass())
        is_array = self.getAIRRMap().getMapping(key, self.getAIRRTag(),
                               "airr_is_array", self.getAIRRMap().getRepertoireClass())
        # If we are not doing strict typing, then if the key is not an AIRR
        # key (field_type == None) then we return True. This allows us to
        # check AIRR keys only and skip non-AIRR keys. If strict checking is
        # on, then if we find a non-AIRR key, we return False, as this is
        # checking AIRR typing explicitly, not typing in general.
        if field_type is None:
            if strict: return False
            else: return True

        # If the value is null and the field is nullable or there is no nullable
        # entry in the AIRR mapping (meaning NULL is OK) then return True.
        if (not isinstance(value, (list))and
            pd.isnull(value) and
            (field_nullable == None or field_nullable)):
            return True

        # If we get here, we have an AIRR field, so no matter what we 
        # return False if the type doesn't match.
        valid_type = False
        if isinstance(value, (str)) and field_type == "string":
            valid_type = True
        elif isinstance(value, (bool,np.bool_)) and field_type == "boolean":
            valid_type = True
        elif isinstance(value, (int,np.integer)) and field_type == "integer":
            valid_type = True
        elif isinstance(value, (float,int,np.floating,np.integer)) and field_type == "number":
            # We need to accept integers and floats as numbers.
            valid_type = True
        elif isinstance(value, (list)) and is_array:
            # List is a special case, we only have arrays of strings.
            # Iterate and check each value
            valid_type = True
            for element in value:
                if not self.validAIRRFieldType(key, element, strict):
                    valid_type = False

        if self.verbose():
            if not isinstance(value, (list)) and pd.isnull(value):
                print("Info: Field %s type ERROR, null value, field is non-nullable"%
                      (key))
            elif not valid_type:
                print("Info: Field %s type ERROR, expected %s, got %s"%
                      (key, field_type, str(type(value))))
        return valid_type

    # Hide the impementation of the repository from the Repertoire subclasses.
    # The subclasses don't ask much of the repository, just insert a single
    # JSON document at a time. Returns a record_id on success, None on failure
    def repositoryInsertRepertoire( self, json_document ):
    
        # Check to see if the repertoire already exists. We do this by using
        # the rearrangement file field and check to see if the file field
        # already exists in another record or not...
        # First get the file field we use to connect rearrangments and reperotires
        rearrangement_file_field = self.getRearrangementFileField()
        # Then get the repository field
        file_repository_field = self.getAIRRMap().getMapping(rearrangement_file_field,
                                                        self.getiReceptorTag(),
                                                        self.getRepositoryTag())
        # Also get the field that links repertoires to rearrangements
        link_field = self.getRepertoireLinkIDField()
        # Map it to a repository field
        link_repository_field = self.getAIRRMap().getMapping(link_field,
                                                             self.getiReceptorTag(),
                                                             self.getRepositoryTag())
        # Then get the actual files that belong to this repertoire.
        file_names = json_document[file_repository_field]
        # Check to see if there are files in the file field. If not, then pring a warning
        # as we won't be able to link any rearrangements to this repertoire. We set an empty
        # array as we want to still insert the record with the following warning...
        if file_names is None or file_names == "":
            print("Warning: Repertoire does not have any rearrangement files.")
            print("Warning:     Will not be able to link rearrangements to this repertoire")
            idarray = []
        else:
            # Finally we search for and get a list of the repertoires that have the files.
            idarray = self.repositoryGetRepertoireIDs(file_repository_field, file_names)

        # If idarray is None, there was a problem with the query.
        if idarray is None:
            print("ERROR: Unable to check for repertoire existance for file %s"%(file_names))
            print("ERROR:     Repertoires must have valid rearrangement files.")
            print("ERROR:     Rearrangement files must be unique in the repository.")
            return None

        # The number of repertoires should be 0 other wise it already exists. Fail if
        # the number is not 0.
        num_repertoires = len(idarray)
        # Get some info to help write out messages
        study_tag = self.getAIRRMap().getMapping("study_id",
                                                 self.getiReceptorTag(),
                                                 self.getRepositoryTag())
        study = "NULL" if not study_tag in json_document else json_document[study_tag]
        sample_tag = self.getAIRRMap().getMapping("sample_id", self.getiReceptorTag(),
                                                  self.getRepositoryTag())
        sample = "NULL" if not sample_tag in json_document else json_document[sample_tag]
        # Print an error if record already exists and we are NOT updating the record.
        if not self.repository.updateOnly() and not num_repertoires == 0:
            print("ERROR: Unable to write repertoire, already exists in the repository")
            print("ERROR:     Write failed for study '%s', sample '%s'"%(study, sample))
            print("ERROR:     File field %s contains rearrangement files %s"%
                  (rearrangement_file_field, file_names))
            print("ERROR:     Files found in records with record IDs %s"%(str(idarray)))
            return None

        # Get the repertoire, data_processing, and sample_processing IDs for the record
        # being inserted.
        rep_id_field =  self.getAIRRMap().getMapping("repertoire_id",
                                              self.getAIRRTag(),
                                              self.getRepositoryTag(),
                                              self.getAIRRMap().getRepertoireClass())
        if rep_id_field is None:
            print("ERROR: Could not find \"repertoire_id\" field in mapping (%s -> %s)"%
                  (self.getAIRRTag(), self.getRepositoryTag()))
            return None

        data_id_field =  self.getAIRRMap().getMapping("data_processing_id",
                                              self.getAIRRTag(),
                                              self.getRepositoryTag(),
                                              self.getAIRRMap().getRepertoireClass())
        sample_id_field =  self.getAIRRMap().getMapping("sample_processing_id",
                                              self.getAIRRTag(),
                                              self.getRepositoryTag(),
                                              self.getAIRRMap().getRepertoireClass())
        if rep_id_field in json_document:
            repertoire_id = json_document[rep_id_field]
            if repertoire_id == "":
                repertoire_id = None
        else: repertoire_id = None

        if data_id_field in json_document:
            data_processing_id = json_document[data_id_field]
            if data_processing_id == "":
                data_processing_id = None
        else: data_processing_id = None

        if sample_id_field in json_document:
            sample_processing_id = json_document[sample_id_field]
            if sample_processing_id == "":
                sample_processing_id = None
        else: sample_processing_id = None

        # Get the number of repertoires for the current repertoire_id.
        rep_array = self.repositoryGetRepertoires(rep_id_field, repertoire_id)
        num_repertoires = len(rep_array)

        # If we are updating, we want one, and only one record.
        if self.repository.updateOnly():
            # If we areupdating we want the record to be unique. repertoire_id is
            # not sufficient so we have to check and see if the repertoire_id,
            # data_processing_id, and sample_processing_id is unique
            if num_repertoires == 0:
                print("ERROR: Could not find Reperotire %s to update"%(repertoire_id))
                return None
            elif num_repertoires == 1:
                rep = rep_array[0]
                link_repository_value = rep[link_repository_field]
            elif num_repertoires > 1:
                link_repository_value = None
                for rep in rep_array:
                    # If we found the correct repertoire, keep track of its "link_field"
                    # as that is the unique repository identifier we use to update that field.
                    if (rep[sample_id_field]==sample_processing_id and 
                        rep[data_id_field]==data_processing_id and
                        rep[rep_id_field]==repertoire_id):
                        if link_repository_value == None:
                            link_repository_value = rep[link_repository_field]
                        else:
                            print("ERROR: Found more than one repertoire with:")
                            print("ERROR:     repertoire_id = %s"%(repertoire_id))
                            print("ERROR:     sample_processing_id = %s"%(sample_processing_id))
                            print("ERROR:     data_processing_id = %s"%(data_processing_id))
                            return None

            # Store in our internal field the update time.
            json_document["ir_updated_at"] = self.getDateTimeNowUTC()

            if self.verbose():
                print("Info: Updating Repertoire:")
                print("Info:     %s = %s"% (link_repository_field, link_repository_value))
                print("Info:     %s = %s"% (rep_id_field, repertoire_id))
                print("Info:     %s = %s"% (data_id_field, data_processing_id))
                print("Info:     %s = %s"% (sample_id_field, sample_processing_id))
            record_id = self.repository.updateRepertoire(link_repository_field,
                                                         link_repository_value,
                                                         json_document)
            return record_id
        else:

            # If we are inserting, we want the new record to not exist. If we are
            # updating we want the record to be unique. repertoire_id is not sufficient
            # so we have to check and see if the repertoire_id, data_processing_id, and
            # sample_processing_id to confirm uniqueness (update) or missing (insert). 
            if not num_repertoires == 0:
                duplicate = True
                for rep in rep_array:
                    #print("new = -%s- -%s- -%s-"%
                    #      (repertoire_id, data_processing_id, sample_processing_id))
                    #print("current = -%s- -%s- -%s-"%
                    #      (rep[rep_id_field],
                    #       rep[data_id_field],
                    #       rep[sample_id_field]))
                    # Check if the repertoire found has a different data_processing_id, if
                    # so then this is not a conflict for insertion.
                    if (data_id_field in rep and
                            not rep[data_id_field] == data_processing_id and
                            not rep[data_id_field] == "" and
                            not data_processing_id is None and
                            not data_processing_id == ""):
                        #print("DIFFERENT DATA_PROC")
                        duplicate = False
                    # Check if the repertoire found has a different sample_processing_id, if
                    # so then this is not a conflict for insertion.
                    elif (sample_id_field in rep and
                            not rep[sample_id_field] == sample_processing_id and
                            not rep[sample_id_field] == "" and
                            not sample_processing_id is None and
                            not sample_processing_id == ""):
                        #print("DIFFERENT SAMPLE_PROC")
                        duplicate = False
    
                if duplicate:
                    print("ERROR: Unable to confirm uniqieness of repertoire in repository")
                    print("ERROR:     Write failed for study '%s', sample '%s'"%(study, sample))
                    print("ERROR:     Trying to write a record with fields:")
                    print("ERROR:         %s = %s"% (rep_id_field, repertoire_id))
                    print("ERROR:         %s = %s"% (data_id_field, data_processing_id))
                    print("ERROR:         %s = %s"% (sample_id_field, sample_processing_id))
                    print("ERROR:     Unable to differentiate from repository record:")
                    print("ERROR:         %s = %s"% (rep_id_field, rep[rep_id_field]))
                    print("ERROR:         %s = %s"% (data_id_field, rep[data_id_field]))
                    print("ERROR:         %s = %s"% (sample_id_field, rep[sample_id_field]))
                    return None

            # Store in our internal field the creation and update time.
            json_document["ir_updated_at"] = self.getDateTimeNowUTC()
            json_document["ir_created_at"] = self.getDateTimeNowUTC()

            # Initialize the internal rearrangement count field to 0
            rearrangement_count_field = self.getRearrangementCountField()
            count_field = self.getAIRRMap().getMapping(rearrangement_count_field,
                                                       self.getiReceptorTag(),
                                                       self.getRepositoryTag())
            if count_field is None:
                print("Warning: Could not find %s field in repository, not initialized"
                      %(rearrangement_count_field, repository_tag))
            else:
                json_document[count_field] = 0

            # Try to write the record and return record_id as appropriate.
            record_id = self.repository.insertRepertoire(json_document, link_repository_field)
            if record_id is None:
                print("ERROR: Unable to write repertoire record to repository")
                return None

            # Update the _id fields if they were empty to force uniqueness. To do this we use
            # the record_id which is guaranteed to be unique in the repository.
            if repertoire_id is None:
                self.repository.updateField(link_repository_field, record_id,
                                            rep_id_field, str(record_id))
            if data_processing_id is None:
                self.repository.updateField(link_repository_field, record_id,
                                            data_id_field, str(record_id))
            if sample_processing_id is None:
                self.repository.updateField(link_repository_field, record_id,
                                            sample_id_field, str(record_id))
            if self.verbose:
                print("Info: Successfully wrote repertoire record <%s, %s, %s>" %
                      (study, sample, file_names))

            # Return the record ID
            return record_id


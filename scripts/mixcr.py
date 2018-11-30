# Script for loading MIXCR formatted annotation file 
# into an iReceptor data node MongoDb database
#

import sys
import os.path
import pandas as pd
import json
import gzip
import time

from parser import Parser

class MiXCR(Parser):
    
    def __init__( self, context ):
        Parser.__init__(self,context)

    def process(self):

        # This first iteration just reads one MiXCR file
        # at a time, given the full file (path) name
        # e.g. SRR4084213_aa_mixcr_annotation.txt
        # May also be gzip compressed file
        
        # Open, decompress then read(), if it is a gz archive
        success = True

        # Check to see if the file exists and return if not.
        if not os.path.isfile(self.context.path):
            print("Could not open MiXCR file ", self.context.path)
            return False

        # Get root filename from the path, should be a file if the path is file, so not checking again 8-)
        filename = os.path.basename(self.context.path)

        if self.context.path.endswith(".gz"):
            print("Reading data gzip archive: "+self.context.path)
            with gzip.open(self.context.path, 'rb') as file_handle:
                # read file directly from the file handle 
                # (Panda read_table call handles this...)
                success = self.processMiXcrFile(file_handle, filename)

        else: # read directly as a regular text file
            print("Reading text file: "+self.context.path)
            file_handle = open(self.context.path, "r")
            success = self.processMiXcrFile(file_handle, filename)

        return success

    def processMiXcrFile( self, file_handle, filename ):

        # Define the number of records to iterate over
        chunk_size = 100000

        # Query for the sample and create an array of sample IDs
        filename = filename.replace(".gz", "")
        print("Retrieving associated sample for file", filename)
        samples_cursor = self.context.samples.find({"mixcr_file_name":{'$regex': filename}},{'_id':1})
        idarray = [sample['_id'] for sample in samples_cursor]

        # Check to see that we found it and that we only found one. Fail if not.
        num_samples = len(idarray)
        if num_samples == 0:
            print("Could not find annotation file", filename)
            print("No sample could be associated with this annotation file.")
            return False
        elif num_samples > 1:
            print("Annotation file can not be associated with a unique sample, found", num_samples)
            print("Unique assignment of annotations to a single sample are required.")
            return False

        # Get the sample ID and assign it to sample ID field
        ir_project_sample_id = idarray[0]

        # Extract the fields that are of interest for this file. Essentiall all non null mixcr fields
        field_of_interest = self.context.airr_map.airr_rearrangement_map['mixcr'].notnull()

        # We select the rows in the mapping that contain fields of interest for MiXCR.
        # At this point, file_fields contains N columns that contain our mappings for the
        # the specific formats (e.g. ir_id, airr, vquest). The rows are limited to have
        # only data that is relevant to MiXCR
        file_fields = self.context.airr_map.airr_rearrangement_map.loc[field_of_interest]

        # We need to build the set of fields that the repository can store. We don't
        # want to extract fields that the repository doesn't want.
        mixcrColumns = []
        columnMapping = {}
        for index, row in file_fields.iterrows():
            if self.context.verbose:
                print("    " + str(row['mixcr']) + " -> " + str(row['ir_turnkey']))
            # If the repository column has a value for the IMGT field, track the field
            # from both the IMGT and repository side.
            if not pd.isnull(row['ir_turnkey']):
                mixcrColumns.append(row['mixcr'])
                columnMapping[row['mixcr']] = row['ir_turnkey']
            else:
                print("Repository does not support " +
                      str(row['mixcr']) + ", not inserting into repository")

	# Get a Pandas reader iterator for the file. When reading the file we only want to
        # read in the mixcrColumns we care about. We want to read in only a fixed number of 
        # records so we don't have any memory contraints reading really large files. And
        # we don't want to map empty strings to Pandas NaN values. This causes an issue as
        # missing strings get read as a NaN value, which is interpreted as a string. One can
        # then not tell the difference between a "nan" string and a "NAN" Junction sequence.
        print("Preparing the file reader...", flush=True)
        df_reader = pd.read_table(file_handle, usecols=mixcrColumns, chunksize=chunk_size, na_filter=False)

        # Iterate over the file a chunk at a time. Each chunk is a data frame.
        total_records = 0
        for df_chunk in df_reader:

            if self.context.verbose:
                print("Processing raw data frame...", flush=True)
            # Remap the column names. We need to remap because the columns may be in a differnt
            # order in the file than in the column mapping.
            df_chunk.rename(columnMapping, axis='columns', inplace=True)

            # Build the substring array that allows index for fast searching of
            # Junction AA substrings. Also calculate junction AA length
            if 'junction_aa' in df_chunk:
                if self.context.verbose:
                    print("Computing junction amino acids substrings...", flush=True)
                df_chunk['substring'] = df_chunk['junction_aa'].apply(Parser.get_substring)
                if self.context.verbose:
                    print("Computing junction amino acids length...", flush=True)
                df_chunk['junction_aa_length'] = df_chunk['junction_aa'].apply(str).apply(len)

            # MiXCR doesn't have junction nucleotide length, we want it in our repository.
            if 'junction_nt' in df_chunk:
                if self.context.verbose:
                    print("Computing junction length...", flush=True)
                df_chunk['junction_length'] = df_chunk['junction_nt'].apply(str).apply(len)


            # Build the v_call field, as an array if there is more than one gene
            # assignment made by the annotator.
            Parser.processGene(self.context, df_chunk, "v_call", "v_call", "vgene_gene", "vgene_family")
            Parser.processGene(self.context, df_chunk, "j_call", "j_call", "jgene_gene", "jgene_family")
            Parser.processGene(self.context, df_chunk, "d_call", "d_call", "dgene_gene", "dgene_family")

            # Assign each record the constant fields for all records in the chunk
            df_chunk['functional'] = 1
            # Assign any iReceptor specific custom fields for the records in the chunk
            df_chunk['ir_annotation_tool'] = 'MiXCR'
            df_chunk['ir_project_sample_id'] = ir_project_sample_id

            # Insert the chunk of records into Mongo.
            num_records = len(df_chunk)
            print("Inserting", num_records, "records into Mongo...", flush=True)
            t_start = time.perf_counter()
            records = json.loads(df_chunk.T.to_json()).values()
            self.context.sequences.insert_many(records)
            t_end = time.perf_counter()
            print("Inserted records, time =", (t_end - t_start), "seconds", flush=True)

            # Keep track of the total number of records processed.
            total_records = total_records + num_records

        print("Total records loaded =", total_records, flush=True)

        # Get the number of annotations for this repertoire (as defined by the ir_project_sample_id)
        if self.context.verbose:
            print("Getting the number of annotations for this repertoire")
        annotation_count = self.context.sequences.find(
                {"ir_project_sample_id":{'$eq':ir_project_sample_id}}
            ).count()
        if self.context.verbose:
            print("Annotation count = %d" % (annotation_count))

        # Set the cached ir_sequeunce_count field for the repertoire/sample.
        self.context.samples.update(
            {"_id":ir_project_sample_id}, {"$set": {"ir_sequence_count":annotation_count}}
        )

        print("MiXCR data loading complete for file: "+filename, flush=True)
        return True
        

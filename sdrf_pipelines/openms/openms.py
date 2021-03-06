import re
from collections import Counter
from sdrf_pipelines.openms.unimod import UnimodDatabase

#example: parse_sdrf convert-openms -s .\sdrf-pipelines\sdrf_pipelines\large_sdrf.tsv -c '[characteristics[biological replicate],characteristics[individual]]'

import pandas as pd

class FileToColumnEntries:
    file2mods = dict()
    file2pctol = dict()
    file2pctolunit = dict()
    file2fragtol = dict()
    file2fragtolunit = dict()
    file2diss = dict()
    file2enzyme = dict()
    file2fraction = dict()
    file2label = dict()
    file2source = dict()
    file2combined_factors = dict()
    file2technical_rep = dict()

class OpenMS:

  def __init__(self) -> None:
    super().__init__()
    self.warnings = dict()
    self._unimod_database = UnimodDatabase()


  # convert modifications in sdrf file to OpenMS notation
  def openms_ify_mods(self, sdrf_mods):
    oms_mods = list()

    for m in sdrf_mods:
      if "AC=UNIMOD" not in m and "AC=Unimod" not in m:
        raise Exception("only UNIMOD modifications supported. " + m)

      name = re.search("NT=(.+?)(;|$)", m).group(1)
      name = name.capitalize()

      accession = re.search("AC=(.+?)(;|$)", m).group(1)
      ptm = self._unimod_database.get_by_accession(accession)
      if ptm != None:
        name = ptm.get_name()

      # workaround for missing PP in some sdrf TODO: fix in sdrf spec?
      if re.search("PP=(.+?)[;$]", m) is None:
        pp = "Anywhere"
      else:
        pp = re.search("PP=(.+?)(;|$)", m).group(
          1)  # one of [Anywhere, Protein N-term, Protein C-term, Any N-term, Any C-term

      if re.search("TA=(.+?)(;|$)", m) is None:  # TODO: missing in sdrf.
        warning_message = "Warning no TA= specified. Setting to N-term or C-term if possible."
        self.warnings[warning_message] = self.warnings.get(warning_message, 0) + 1
        if "C-term" in pp:
          ta = "C-term"
        elif "N-term" in pp:
          ta = "N-term"
        else:
          warning_message = "Reassignment not possible. Skipping."
          # print(warning_message + " "+ m)
          self.warnings[warning_message] = self.warnings.get(warning_message, 0) + 1
          pass
      else:
        ta = re.search("TA=(.+?)(;|$)", m).group(1)  # target amino-acid
      aa = ta.split(",")  # multiply target site e.g., S,T,Y including potentially termini "C-term"

      if pp == "Protein N-term" or pp == "Protein C-term":
        for a in aa:
          if a == "C-term" or a == "N-term":  # no site specificity
            oms_mods.append(name + " (" + pp + ")")  # any Protein N/C-term
          else:
            oms_mods.append(name + " (" + pp + " " + a + ")")  # specific Protein N/C-term
      elif pp == "Any N-term" or pp == "Any C-term":
        pp = pp.replace("Any ", "")  # in OpenMS we just use N-term and C-term
        for a in aa:
          if a == "C-term" or aa == "N-term":  # no site specificity
            oms_mods.append(name + " (" + pp + ")")  # any N/C-term
          else:
            oms_mods.append(name + " (" + pp + " " + a + ")")  # specific N/C-term
      else:  # Anywhere in the peptide
        for a in aa:
          oms_mods.append(name + " (" + a + ")")  # specific site in peptide

    return ",".join(oms_mods)

  def openms_convert(self, sdrf_file: str = None, keep_raw: bool = False, one_table: bool = False, legacy: bool = False,
                     verbose: bool = False, split_by_columns: str = None):

    print('PROCESSING: ' + sdrf_file + '"')

    # convert list passed on command line '[assay name,comment[fraction identifier]]' to python list
    if split_by_columns:
      split_by_columns = split_by_columns[1:-1]  # trim '[' and ']'
      split_by_columns = split_by_columns.split(',')
      for i, value in enumerate(split_by_columns):
        split_by_columns[i] = value
      print('User selected factor columns: ' + str(split_by_columns))

    # load sdrf file
    sdrf = pd.read_table(sdrf_file)
    sdrf = sdrf.astype(str)
    sdrf.columns = map(str.lower, sdrf.columns)  # convert column names to lower-case

    # map filename to tuple of [fixed, variable] mods
    mod_cols = [c for ind, c in enumerate(sdrf) if
                c.startswith('comment[modification parameters')]  # columns with modification parameters


    if not split_by_columns:
      # get factor columns (except constant ones)
      factor_cols = [c for ind, c in enumerate(sdrf) if c.startswith('factor value[') and len(sdrf[c].unique()) > 1]

      # get characteristics columns (except constant ones)
      characteristics_cols = [c for ind, c in enumerate(sdrf) if
                              c.startswith('characteristics[') and len(sdrf[c].unique()) > 1]
      # and remove characteristics columns already present as factor
      characteristics_cols, f = self.removeRedundantCharacteristics(characteristics_cols, sdrf, factor_cols)
      print('Factor columns: ' + str(factor_cols))  
      print('Characteristics columns (those covered by factor columns removed): ' + str(characteristics_cols))
    else:
      factor_cols = split_by_columns # enforce columns as factors if names provided by user

    source_name_list = list()
    source_name2n_reps = dict()

    f2c = FileToColumnEntries()

    for row_index, row in sdrf.iterrows():
      ## extract mods
      all_mods = list(row[mod_cols])
      # print(all_mods)
      var_mods = [m for m in all_mods if 'MT=variable' in m or 'MT=Variable' in m]  # workaround for capitalization
      var_mods.sort()
      fixed_mods = [m for m in all_mods if 'MT=fixed' in m or 'MT=Fixed' in m]  # workaround for capitalization
      fixed_mods.sort()
      if verbose:
        print(row)
      raw = row['comment[data file]']
      fixed_mods_string = ""
      if fixed_mods is not None:
        fixed_mods_string = self.openms_ify_mods(fixed_mods)

      variable_mods_string = ""
      if var_mods is not None:
        variable_mods_string = self.openms_ify_mods(var_mods)

      f2c.file2mods[raw] = (fixed_mods_string, variable_mods_string)

      source_name = row['source name']
      f2c.file2source[raw] = source_name
      if not source_name in source_name_list:
        source_name_list.append(source_name)

      if 'comment[precursor mass tolerance]' in row:
        pc_tol_str = row['comment[precursor mass tolerance]']
        if "ppm" in pc_tol_str or "Da" in pc_tol_str:
          pc_tmp = pc_tol_str.split(" ")
          f2c.file2pctol[raw] = pc_tmp[0]
          f2c.file2pctolunit[raw] = pc_tmp[1]
        else:
          warning_message = "Invalid precursor mass tolerance set. Assuming 10 ppm."
          self.warnings[warning_message] = self.warnings.get(warning_message, 0) + 1
          f2c.file2pctol[raw] = "10"
          f2c.file2pctolunit[raw] = "ppm"
      else:
        warning_message = "No precursor mass tolerance set. Assuming 10 ppm."
        self.warnings[warning_message] = self.warnings.get(warning_message, 0) + 1
        f2c.file2pctol[raw] = "10"
        f2c.file2pctolunit[raw] = "ppm"

      if 'comment[fragment mass tolerance]' in row:
        f_tol_str = row['comment[fragment mass tolerance]']
        f_tol_str.replace("PPM", "ppm")  # workaround
        if "ppm" in f_tol_str or "Da" in f_tol_str:
          f_tmp = f_tol_str.split(" ")
          f2c.file2fragtol[raw] = f_tmp[0]
          f2c.file2fragtolunit[raw] = f_tmp[1]
        else:
          warning_message = "Invalid fragment mass tolerance set. Assuming 20 ppm."
          self.warnings[warning_message] = self.warnings.get(warning_message, 0) + 1
          f2c.file2fragtol[raw] = "20"
          f2c.file2fragtolunit[raw] = "ppm"
      else:
        warning_message = "No fragment mass tolerance set. Assuming 20 ppm."
        self.warnings[warning_message] = self.warnings.get(warning_message, 0) + 1
        f2c.file2fragtol[raw] = "20"
        f2c.file2fragtolunit[raw] = "ppm"

      if 'comment[dissociation method]' in row:
        diss_method = re.search("NT=(.+?)(;|$)", row['comment[dissociation method]']).group(1)
        f2c.file2diss[raw] = diss_method.upper()
      else:
        warning_message = "No dissociation method provided. Assuming HCD."
        self.warnings[warning_message] = self.warnings.get(warning_message, 0) + 1
        f2c.file2diss[raw] = 'HCD'

      if 'comment[technical replicate]' in row:
        technical_replicate = str(row['comment[technical replicate]'])
        if "not available" in technical_replicate:
          f2c.file2technical_rep[raw] = "1"
        else:
          f2c.file2technical_rep[raw] = technical_replicate
      else:
        f2c.file2technical_rep[raw] = "1"

      # store highest replicate number for this source name
      if source_name in source_name2n_reps:
        source_name2n_reps[source_name] = max(int(source_name2n_reps[source_name]), int(f2c.file2technical_rep[raw]))
      else:
        source_name2n_reps[source_name] = int(f2c.file2technical_rep[raw])

      enzyme = re.search("NT=(.+?)(;|$)", row['comment[cleavage agent details]']).group(1)
      enzyme = enzyme.capitalize()
      if "Trypsin/p" in enzyme:  # workaround
        enzyme = "Trypsin/P"
      f2c.file2enzyme[raw] = enzyme

      if 'comment[fraction identifier]' in row:
        fraction = str(row['comment[fraction identifier]'])
        if "not available" in fraction:
          f2c.file2fraction[raw] = "1"
        else:
          f2c.file2fraction[raw] = fraction
      else:
        f2c.file2fraction[raw] = "1"

      label = re.search("NT=(.+?)(;|$)", row['comment[label]']).group(1)
      f2c.file2label[raw] = label

      if not split_by_columns:
        # extract factors (or characteristics if factors are missing), and generate one condition for
        # every combination of factor values present in the data
        combined_factors = self.combine_factors_to_conditions(characteristics_cols, factor_cols, row)
      else:
        # take only only entries of splitting columns to generate the conditions
        combined_factors = "|".join(list(row[split_by_columns]))

      # add condition from factors as extra column to sdrf so we can easily filter in pandas
      sdrf.at[row_index, "_conditions_from_factors"] = combined_factors
      f2c.file2combined_factors[raw] = combined_factors

      #print("Combined factors: " + str(combined_factors))

    conditions = Counter(f2c.file2combined_factors.values()).keys()
    files_per_condition = Counter(f2c.file2combined_factors.values()).values()
    print("Conditions (" + str(len(conditions)) + "): " + str(conditions))
    print("Files per condition: " + str(files_per_condition))

    ##################### only label-free supported right now

    if not split_by_columns:
      # output of search settings for every row in sdrf
      self.save_search_settings_to_file("openms.tsv", sdrf, f2c)

      # output one experimental design file
      if one_table:
        self.writeOneTableExperimentalDesign("experimental_design.tsv", legacy, sdrf, f2c.file2technical_rep, source_name_list, source_name2n_reps, f2c.file2combined_factors, f2c.file2label, raw, keep_raw, f2c.file2fraction)
      else:  # two table format
        self.writeTwoTableExperimentalDesign("experimental_design.tsv", sdrf, f2c.file2technical_rep, source_name_list, source_name2n_reps, f2c.file2label, raw, keep_raw, f2c.file2fraction, f2c.file2combined_factors)

    else: # split by columns
      for index, c in enumerate(conditions):
        # extract rows from sdrf for current condition
        split_sdrf = sdrf.loc[sdrf["_conditions_from_factors"] == c]
        output_filename = "openms.tsv." + str(index)
        self.save_search_settings_to_file(output_filename, split_sdrf, f2c)

        # output of experimental design
        output_filename = "experimental_design.tsv." + str(index)
        if one_table:
          self.writeOneTableExperimentalDesign(output_filename, legacy, split_sdrf, f2c.file2technical_rep, source_name_list,
                                               source_name2n_reps, f2c.file2combined_factors, f2c.file2label, raw,
                                               keep_raw, f2c.file2fraction)
        else:  # two table format
          self.writeTwoTableExperimentalDesign(output_filename,split_sdrf, f2c.file2technical_rep, source_name_list, source_name2n_reps,
                                               f2c.file2label, raw, keep_raw, f2c.file2fraction,
                                               f2c.file2combined_factors)


    self.reportWarnings(sdrf_file)

  def combine_factors_to_conditions(self, characteristics_cols, factor_cols, row):
    all_factors = list(row[factor_cols])
    combined_factors = "|".join(all_factors)
    if combined_factors == "":
      # fallback to characteristics (use them as factors)
      all_factors = list(row[characteristics_cols])
      combined_factors = "|".join(all_factors)
      if combined_factors == "":
        warning_message = "No factors specified. Adding dummy factor used as condition."
        self.warnings[warning_message] = self.warnings.get(warning_message, 0) + 1
        combined_factors = "none"
      else:
        warning_message = "No factors specified. Adding non-redundant characteristics as factor. Will be used as condition."
        self.warnings[warning_message] = self.warnings.get(warning_message, 0) + 1
    return combined_factors

  def removeRedundantCharacteristics(self, characteristics_cols, sdrf, factor_cols):
    redundant_characteristics_cols = set()
    for c in characteristics_cols:
      c_col = sdrf[c]  # select characteristics column
      for f in factor_cols:  # Iterate over all factor columns
        f_col = sdrf[f]  # select factor column
        if c_col.equals(f_col):
          redundant_characteristics_cols.add(c)
    characteristics_cols = [x for x in characteristics_cols if x not in redundant_characteristics_cols]
    return characteristics_cols, f

  def reportWarnings(self, sdrf_file):
    if len(self.warnings) != 0:
      for k, v in self.warnings.items():
        print('WARNING: "' + k + '" occured ' + str(v) + ' times.')
    print("SUCCESS (WARNINGS=" + str(len(self.warnings)) + "): " + sdrf_file)

  def writeTwoTableExperimentalDesign(self, output_filename, sdrf, file2technical_rep, source_name_list, source_name2n_reps, file2label, raw, keep_raw, file2fraction, file2combined_factors):
    f = open(output_filename, "w+")
    raw_ext_regex = re.compile(r"\.raw$", re.IGNORECASE)

    openms_file_header = ["Fraction_Group", "Fraction", "Spectra_Filepath", "Label", "Sample"]
    f.write("\t".join(openms_file_header) + "\n")

    for _0, row in sdrf.iterrows():  # does only work for label-free not for multiplexed. TODO
      raw = row["comment[data file]"]
      source_name = row["source name"]
      replicate = file2technical_rep[raw]

      # calculate fraction group by counting all technical replicates of the preceeding source names
      source_name_index = source_name_list.index(source_name)
      offset = 0
      for i in range(source_name_index):
        offset = offset + int(source_name2n_reps[source_name_list[i]])

      fraction_group = str(offset + int(replicate))
      sample = fraction_group  # TODO: change this for multiplexed

      label = file2label[raw]
      if "label free sample" in label:
        label = "1"

      if not keep_raw:
        out = raw_ext_regex.sub(".mzML", raw)
      else:
        out = raw

      f.write(fraction_group + "\t" + file2fraction[raw] + "\t" + out + "\t" + label + "\t" + sample + "\n")

    # sample table
    f.write("\n")
    openms_sample_header = ["Sample", "MSstats_Condition", "MSstats_BioReplicate"]
    f.write("\t".join(openms_sample_header) + "\n")
    sample_row_written = list()
    for _0, row in sdrf.iterrows():  # does only work for label-free not for multiplexed. TODO
      raw = row["comment[data file]"]
      source_name = row["source name"]
      replicate = file2technical_rep[raw]

      # calculate fraction group by counting all technical replicates of the preceeding source names
      source_name_index = source_name_list.index(source_name)
      offset = 0
      for i in range(source_name_index):
        offset = offset + int(source_name2n_reps[source_name_list[i]])

      fraction_group = str(offset + int(replicate))
      sample = fraction_group  # TODO: change this for multiplexed

      if 'none' in file2combined_factors[raw]:
        # no factor defined use sample as condition
        condition = sample
      else:
        condition = file2combined_factors[raw]

      # MSstats BioReplicate column needs to be different for samples from different conditions.
      # so we can't just use the technical replicate identifier in sdrf but use the sample identifer
      MSstatsBioReplicate = sample

      if sample not in sample_row_written:
        f.write(sample + "\t" + condition + "\t" + MSstatsBioReplicate + "\n")
        sample_row_written.append(sample)

    f.close()

  def writeOneTableExperimentalDesign(self, output_filename, legacy, sdrf, file2technical_rep, source_name_list, source_name2n_reps, file2combined_factors, file2label, raw, keep_raw, file2fraction):
    f = open(output_filename, "w+")
    raw_ext_regex = re.compile(r"\.raw$", re.IGNORECASE)

    if legacy:
      open_ms_experimental_design_header = ["Fraction_Group", "Fraction", "Spectra_Filepath", "Label", "Sample",
                                            "MSstats_Condition", "MSstats_BioReplicate"]
    else:
      open_ms_experimental_design_header = ["Fraction_Group", "Fraction", "Spectra_Filepath", "Label",
                                            "MSstats_Condition", "MSstats_BioReplicate"]
    f.write("\t".join(open_ms_experimental_design_header) + "\n")

    for _0, row in sdrf.iterrows():  # does only work for label-free not for multiplexed. TODO
      raw = row["comment[data file]"]
      source_name = row["source name"]
      replicate = file2technical_rep[raw]

      # calculate fraction group by counting all technical replicates of the preceeding source names
      source_name_index = source_name_list.index(source_name)
      offset = 0
      for i in range(source_name_index):
        offset = offset + int(source_name2n_reps[source_name_list[i]])

      fraction_group = str(offset + int(replicate))
      sample = fraction_group

      if 'none' in file2combined_factors[raw]:
        # no factor defined use sample as condition
        condition = sample
      else:
        condition = file2combined_factors[raw]
      label = file2label[raw]
      if "label free sample" in label:
        label = "1"

      if not keep_raw:
        out = raw_ext_regex.sub(".mzML", raw)
      else:
        out = raw

      # MSstats BioReplicate column needs to be different for samples from different conditions.
      # so we can't just use the technical replicate identifier in sdrf but use the sample identifer
      MSstatsBioReplicate = sample
      if legacy:
        f.write(fraction_group + "\t" + file2fraction[
          raw] + "\t" + out + "\t" + label + "\t" + sample + "\t" + condition + "\t" + MSstatsBioReplicate + "\n")
      else:
        f.write(fraction_group + "\t" + file2fraction[
          raw] + "\t" + out + "\t" + label + "\t" + condition + "\t" + MSstatsBioReplicate + "\n")
    f.close()

  def save_search_settings_to_file(self, output_filename, sdrf, f2c):
    f = open(output_filename, "w+")
    open_ms_search_settings_header = ["URI", "Filename", "FixedModifications", "VariableModifications", "Label",
                                      "PrecursorMassTolerance", "PrecursorMassToleranceUnit", "FragmentMassTolerance",
                                      "FragmentMassToleranceUnit", "DissociationMethod", "Enzyme"]
    f.write("\t".join(open_ms_search_settings_header) + "\n")
    for _0, row in sdrf.iterrows():  # does only work for label-free not for multiplexed. TODO
      URI = row["comment[file uri]"]
      raw = row["comment[data file]"]
      f.write(URI + "\t" + raw + "\t" + f2c.file2mods[raw][0] + "\t" + f2c.file2mods[raw][1] + "\t" + f2c.file2label[raw] + "\t" +
              f2c.file2pctol[
                raw] + "\t" + f2c.file2pctolunit[raw] + "\t" + f2c.file2fragtol[raw] + "\t" + f2c.file2fragtolunit[raw] + "\t" +
              f2c.file2diss[
                raw] + "\t" + f2c.file2enzyme[raw] + "\n")
    f.close()

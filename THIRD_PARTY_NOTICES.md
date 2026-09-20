# Public reference material

DataLoom code is MIT licensed. Referenced standards retain their own terms.
Bundled code tuples are deliberately small identifier subsets, not complete
terminology distributions or clinical decision support.

- NPI algorithm: [CMS specification, January 23, 2004](https://www.cms.gov/Regulations-and-Guidance/Administrative-Simplification/NationalProvIdentStand/Downloads/NPIcheckdigit.pdf).
  Checksum-valid generated numbers are not verified provider registrations and may collide with issued numbers.
- ICD-10-CM curated identifiers: I10, E11.9, J45.909, R51.9, Z00.00.
  Verified against the [CDC FY2026 code descriptions archive](https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2026/)
  on September 20, 2026. This is a fixed illustrative subset, not an automatically
  updated terminology service.
- LOINC identifiers: [718-7](https://loinc.org/718-7) and [2345-7](https://loinc.org/2345-7).
  LOINC is copyright Regenstrief Institute, Inc. and the Logical Observation
  Identifiers Names and Codes (LOINC) Committee; available under the
  [LOINC license](https://loinc.org/kb/license). LOINC is a registered trademark
  of Regenstrief Institute, Inc. These are unmodified identifiers; local short
  display labels in HL7 messages are not a replacement terminology distribution.
- HL7 builders target [HL7 v2.5](https://www.hl7.eu/HL7v2x/v25/std25/ch03.html).
  They implement minimal structural test profiles, not site-specific conformance.

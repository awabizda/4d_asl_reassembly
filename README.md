# 4D ASL Reassembly

This repository contains a small Python script for organizing scanner DICOM exports and assembling separate ASL control and label series into 4D NIfTI data. It processes multiple subjects and writes results to a `derivatives` folder.

## Script behavior

Run `reassemble_asl.py`. For each subject, it:

- identifies control (`Ctrl`) and label (`Tag` or `Label`) DICOM series;
- groups control and label series by PLD, preferring the Siemens/UIH protocol text such as `PLD2000` and otherwise using DICOM `InversionTime`;
- converts series with `dcm2niix`, orders control and label by DICOM `AcquisitionTime`, and interleaves matching volume pairs with FSL `fslroi` and `fslmerge`;
- creates an ASL JSON sidecar from the Tag JSON, adds missing Ctrl JSON fields, and explicitly takes `RepetitionTimePreparation` from Ctrl when available;
- writes `PostLabelingDelay` in seconds, `M0Type` (`Separate` or `Absent`), and `TotalAcquiredPairs` from the number of converted Tag volumes;
- creates an `_aslcontext.tsv` file;
- converts a separate M0 series when present and adds `IntendedFor` to its JSON; and
- converts optional T1w/MPRAGE data. The recognized T1 pattern includes `t1_gre_fsp_3d_sag_iso1mm`.

Other series, including CBF and subtracted (`Sub`) series, are ignored.

## Input structure

Pass the top-level input directory. It should contain one folder per subject, with each scanner series in its own subfolder:

```text
input/
├── 001/
│   ├── asl_3d_tra_Ctrl_.../
│   ├── asl_3d_tra_Tag_.../
│   ├── asl_3d_tra_M0_.../
│   └── t1_gre_fsp_3d_sag_iso1mm_.../
└── 002/
    └── ...
```

Each series folder must contain DICOM files. Subject folder names become BIDS subject labels: `001` becomes `sub-001`.

## Run

```powershell
python reassemble_asl.py "C:\path\to\input"
```

The script creates `derivatives` inside the input directory. Existing outputs with matching names may be overwritten.

## Output structure

```text
input/
└── derivatives/
    ├── sub-001/
    │   └── ses-PLD2000/
    │       ├── anat/
    │       │   ├── sub-001_ses-PLD2000_T1w.nii.gz
    │       │   └── sub-001_ses-PLD2000_T1w.json
    │       └── perf/
    │           ├── sub-001_ses-PLD2000_asl.nii.gz
    │           ├── sub-001_ses-PLD2000_asl.json
    │           ├── sub-001_ses-PLD2000_aslcontext.tsv
    │           ├── sub-001_ses-PLD2000_m0scan.nii.gz
    │           └── sub-001_ses-PLD2000_m0scan.json
    └── sub-002/
        └── ...
```

`anat` is present only when a recognized T1w series is found. M0 files are also optional. BIDS uses the case-sensitive metadata key `M0Type`. The M0 JSON `IntendedFor` value is written as a BIDS URI pointing to the associated ASL NIfTI, for example `bids::sub-001/ses-PLD2000/perf/sub-001_ses-PLD2000_asl.nii.gz`.

## Dependencies

- Python 3
- `pydicom` (`python -m pip install pydicom`)
- [`dcm2niix`](https://github.com/rordenlab/dcm2niix), available on `PATH`
- FSL, with `fslmerge` and `fslval` available on `PATH`

File handling and JSON use Python's standard library. NIfTI conversion and merging are performed by the external tools above.

## Scope and limitations

- The script expects one input folder per subject and one series subfolder per DICOM series. It does not search multiple subject-folder levels.
- Series recognition uses words in `SeriesDescription`; the T1w check also reads `ProtocolName`. Other scanner naming conventions may need changes to these keywords.
- PLD is read from a `PLD<number>` protocol string when present, otherwise from `InversionTime`. The value is written to BIDS `PostLabelingDelay` in seconds (DICOM time values are commonly in milliseconds). Confirm this interpretation against the acquisition protocol, particularly for other vendors.
- Pairing uses the first available Tag series with a matching PLD. Repeated acquisitions at the same PLD may be paired ambiguously and should be processed separately.
- The script assumes that control and label images have matching volumes and that their order can be inferred from series `AcquisitionTime`. It interleaves corresponding control/label volumes and stops if their counts differ. Check the output data and context file against the acquisition.
- M0 series are assigned to PLDs in order, not matched by acquisition time. Review this when there are multiple PLDs or M0 scans.
- T1w data is converted into each PLD session's `anat` folder, so it can be duplicated when there are multiple PLDs.
- BIDS defines `ArterialSpinLabelingType`, `BackgroundSuppression`, `BackgroundSuppressionNumberPulses`, and `BackgroundSuppressionPulseTime`. The script preserves these when `dcm2niix` supplies them and can read the standard DICOM ASL contrast tag for `ArterialSpinLabelingType`. Vendor-specific values may require private protocol/CSA data or scanner protocol information. If the ASL type or background suppression cannot be inferred, the script prints a warning and leaves the JSON field out; it does not guess.
- This is a lightweight BIDS-like converter, not a full BIDS validator. Review the NIfTI images, JSON metadata, volume order, and links before analysis.

## Metadata references

- [BIDS MRI and ASL specification](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/magnetic-resonance-imaging-data.html)
- [DICOM MR Arterial Spin Labeling Macro](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.13.5.14.html)
- [dcm2niix manufacturer-specific metadata notes](https://github.com/rordenlab/dcm2niix/blob/master/BIDS/README.md)

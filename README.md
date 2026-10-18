# 4D ASL Reassembly

This repository contains a small Python script for organizing scanner DICOM exports and assembling separate ASL control and label series into a 4D NIfTI image. It processes multiple subjects from one input directory and writes results into a `derivatives` folder.

## Script

Run `reassemble_asl.py`. For each subject, it:

- identifies ASL control (`Ctrl`) and label (`Tag` or `Label`) series from their DICOM `SeriesDescription`;
- groups a control series with a label series when their DICOM `InversionTime` values match (used here as the PLD in milliseconds);
- converts each series with `dcm2niix`, orders control and label volumes according to their DICOM `AcquisitionTime`, and joins them with FSL `fslmerge`;
- writes an ASL JSON sidecar based on the Tag JSON, adding fields found only in the Ctrl JSON;
- creates an `_aslcontext.tsv` file whose `volume_type` rows describe the interleaved volumes;
- converts an M0 series when one is present; and
- converts an optional T1w/MPRAGE anatomical series. T1w recognition includes the sample protocol `t1_gre_fsp_3d_sag_iso1mm`.

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

The script searches each series folder recursively for a DICOM file. Subject folder names become subject identifiers; for example, `001` produces `sub-001`.

## Run

```bash
python reassemble_asl.py "\path\to\input"
```

The script creates `derivatives` inside the input directory. Existing outputs with the same names may be overwritten.

## Output structure

```text
input/
└── derivatives/
    ├── sub-001/
    │   ├── PLD2000/
    │   │   ├── anat/
    │   │   │   ├── sub-001_T1w.nii.gz
    │   │   │   └── sub-001_T1w.json
    │   │   └── perf/
    │   │       ├── sub-001_PLD2000_asl.nii.gz
    │   │       ├── sub-001_PLD2000_asl.json
    │   │       ├── sub-001_PLD2000_asl_aslcontext.tsv
    │   │       ├── sub-001_PLD2000_m0scan.nii.gz
    │   │       └── sub-001_PLD2000_m0scan.json
    │   └── PLD1800/
    │       └── ...
    └── sub-002/
        └── ...
```

Anatomical output is optional; it is created only when a recognized T1w/MPRAGE series is found. M0 output is also optional. `dcm2niix` writes the NIfTI and JSON files; file extensions can depend on its output settings/version.

## Dependencies

- Python 3
- `pydicom` (`python -m pip install pydicom`)
- [`dcm2niix`](https://github.com/rordenlab/dcm2niix), available on `PATH`
- FSL, with `fslmerge` and `fslval` available on `PATH`

The script uses Python's standard library for file handling and JSON. It does not use a Python NIfTI library.

## Scope and limitations

- The script expects one scanner export folder per subject and one series folder per DICOM series. It does not search multiple nested subject levels.
- Series are identified by keywords in `SeriesDescription`, plus `ProtocolName` for the supported T1w patterns. Scanner naming conventions that differ may need matching keywords added to the script.
- PLD grouping uses `InversionTime`, from the United Imaging export where 2000 corresponds to PLD2000. This may not represent PLD for every scanner or protocol.
- The script pairs each Ctrl series with the first unused Tag series with the same PLD. If a subject has multiple acquisitions at the same PLD, the pairing may be ambiguous; process those acquisitions separately.
- The context file assumes the two converted series have corresponding volumes and alternate control/label throughout. Check the volume count and context against the acquisition protocol.
- M0 series are assigned to PLDs in order and are not matched using acquisition time. Review this association when there are multiple PLDs or M0 scans.
- A recognized T1w series is copied into every PLD's `anat` folder. It is converted once per PLD, so subjects with many PLDs may have repeated anatomical files.
- The script does not validate image geometry, timing consistency, or BIDS compliance. Review the generated NIfTI images and metadata before analysis.

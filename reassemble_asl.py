"""
    ASL DICOM converter. 
    Dependencies: pydicom, dcm2niix, fslmerge, fslval 
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pydicom


def convert(folder, output, name):
    """Run dcm2niix on one DICOM series folder."""
    subprocess.run([
        "dcm2niix", "-b", "y", "-z", "y", "-f", name,
        "-o", output, folder,
    ], check=True)


def first_dicom(folder):
    """Return one DICOM file's header to read series details."""
    for current, folders, files in os.walk(folder):
        for filename in files:
            path = os.path.join(current, filename)
            try:
                return path, pydicom.dcmread(path, stop_before_pixels=True)
            except Exception:
                pass
    return None, None


def time_number(value):
    """Turn DICOM time HHMMSS.frac into a number for comparing times."""
    return float(str(value).replace(":", "")) if value else 999999


def process_subject(scanner_folder, derivatives_root):
    subject = os.path.basename(os.path.abspath(scanner_folder)).replace("sub-", "")
    output_folder = os.path.join(derivatives_root, "sub-" + subject)
    # The scanner puts one DICOM series in each subfolder. Find its type and PLD.
    series = {"ctrl": [], "tag": [], "m0": [], "t1w": []}
    for folder in os.listdir(scanner_folder):
        path = os.path.join(scanner_folder, folder)
        if not os.path.isdir(path) or folder == "derivatives":
            continue
        dicom_path, header = first_dicom(path)
        if header is None:
            continue

        description = str(getattr(header, "SeriesDescription", folder)).lower()
        protocol = str(getattr(header, "ProtocolName", "")).lower()
        if "ctrl" in description:
            kind = "ctrl"
        elif "tag" in description or "label" in description:
            kind = "tag"
        elif "m0" in description:
            kind = "m0"
        elif ("t1w" in description or "mprage" in description
              or "t1w" in protocol or "mprage" in protocol
              or "t1_gre_fsp_3d_sag_iso1mm" in description
              or "t1_gre_fsp_3d_sag_iso1mm" in protocol):
            kind = "t1w"
        else:
            continue  # Ignore CBF, Sub and every other series.

        # In the sample, InversionTime is 2000 and matches PLD2000 in the
        # United Imaging protocol name (private DICOM field 0065,102D).
        pld = str(getattr(header, "InversionTime", "unknown"))
        if pld.endswith(".0"):
            pld = pld[:-2]
        series[kind].append({"folder": path, "header": header, "pld": pld})

    # Process each Ctrl series and find the Tag series with the same PLD.
    for ctrl in series["ctrl"]:
        pld = ctrl["pld"]
        matching_tags = [item for item in series["tag"] if item["pld"] == pld]
        if not matching_tags:
            print("No matching Tag series for PLD", pld)
            continue
        tag = matching_tags.pop(0)

        # Choose which type goes first by comparing the DICOM acquisition time.
        ctrl_first = time_number(ctrl["header"].AcquisitionTime) < time_number(tag["header"].AcquisitionTime)
        if ctrl_first:
            first, second = ctrl, tag
        else:
            first, second = tag, ctrl

        derivatives = os.path.join(output_folder, "PLD" + pld, "perf")
        os.makedirs(derivatives, exist_ok=True)
        name = "sub-" + subject + "_PLD" + pld + "_asl"

        # Convert each series in a temporary folder, then let FSL merge them.
        with tempfile.TemporaryDirectory() as temp:
            convert(first["folder"], temp, "first")
            convert(second["folder"], temp, "second")
            subprocess.run([
                "fslmerge", "-t", os.path.join(derivatives, name + ".nii.gz"),
                os.path.join(temp, "first.nii.gz"),
                os.path.join(temp, "second.nii.gz"),
            ], check=True)

            # Start with the Tag JSON and add fields that only Ctrl has.
            tag_file = "second.json" if second == tag else "first.json"
            ctrl_file = "first.json" if first == ctrl else "second.json"
            with open(os.path.join(temp, tag_file)) as f:
                tag_json = json.load(f)
            with open(os.path.join(temp, ctrl_file)) as f:
                ctrl_json = json.load(f)
            for key, value in ctrl_json.items():
                if key not in tag_json:
                    tag_json[key] = value
            with open(os.path.join(derivatives, name + ".json"), "w") as f:
                json.dump(tag_json, f, indent=2)

        # Each 3D frame alternates between control and label.
        # The first kind is determined from acquisition time above.
        count = int(subprocess.check_output(["fslval", os.path.join(derivatives, name), "dim4"]).decode().strip())
        with open(os.path.join(derivatives, name + "_aslcontext.tsv"), "w") as context:
            context.write("volume_type\n")
            for i in range(count):
                context.write(("control" if (i % 2 == 0) == ctrl_first else "label") + "\n")

        # Convert the closest M0 series from this scan, if present.
        if series["m0"]:
            m0 = series["m0"].pop(0)
            convert(m0["folder"], derivatives, "sub-" + subject + "_PLD" + pld + "_m0scan")

        print("Created", derivatives)

    # T1w/MPRAGE is optional. Put it under each PLD folder created above.
    for t1w in series["t1w"]:
        for ctrl in series["ctrl"]:
            anat = os.path.join(output_folder, "PLD" + ctrl["pld"], "anat")
            os.makedirs(anat, exist_ok=True)
            convert(t1w["folder"], anat, "sub-" + subject + "_T1w")


def main():
    if len(sys.argv) < 2:
        print("Usage: python reassemble_asl.py INPUT_FOLDER")
        return

    input_folder = os.path.abspath(sys.argv[1])
    derivatives_root = os.path.join(input_folder, "derivatives")

    # The input folder contains one folder per subject.
    for subject_folder in os.listdir(input_folder):
        path = os.path.join(input_folder, subject_folder)
        if os.path.isdir(path) and subject_folder != "derivatives":
            print("Processing", subject_folder)
            process_subject(path, derivatives_root)


if __name__ == "__main__":
    main()

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


def get_pld(header):
    """Find PLD from the UIH protocol tag or fall back to DICOM InversionTime."""
    protocol_tag = header.get((0x0065, 0x102D))
    if protocol_tag and "PLD" in str(protocol_tag.value).upper():
        value = str(protocol_tag.value).upper().split("PLD", 1)[1]
        digits = ""
        for character in value:
            if character.isdigit() or character == ".":
                digits += character
            else:
                break
        if digits:
            return str(int(float(digits)))
    try:
        return str(int(float(header.InversionTime)))
    except (AttributeError, TypeError, ValueError):
        return "unknown"


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

        pld = get_pld(header)
        series[kind].append({"folder": path, "header": header, "pld": pld})

    has_m0 = bool(series["m0"])

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

        session = "ses-PLD" + pld
        derivatives = os.path.join(output_folder, session, "perf")
        os.makedirs(derivatives, exist_ok=True)
        name = "sub-" + subject + "_" + session + "_asl"

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
            if "RepetitionTimePreparation" in ctrl_json:
                tag_json["RepetitionTimePreparation"] = ctrl_json["RepetitionTimePreparation"]

            try:
                tag_json["PostLabelingDelay"] = float(pld) / 1000
            except ValueError:
                print("WARNING: Could not infer PostLabelingDelay for", name)

            tag_json["M0Type"] = "Separate" if has_m0 else "Absent"
            label_file = "second.nii.gz" if second == tag else "first.nii.gz"
            label_count = int(subprocess.check_output([
                "fslval", os.path.join(temp, label_file), "dim4"
            ]).decode().strip())
            tag_json["TotalAcquiredPairs"] = label_count

            # DICOM ASL contrast is a standard source of the BIDS ASL type.
            asl_contrast = tag["header"].get((0x0018, 0x9250))
            if "ArterialSpinLabelingType" not in tag_json and asl_contrast:
                contrast = str(asl_contrast.value).upper()
                if contrast in ("CASL", "PCASL", "PASL"):
                    tag_json["ArterialSpinLabelingType"] = contrast
            if "ArterialSpinLabelingType" not in tag_json:
                print("WARNING: ArterialSpinLabelingType was not found for", name)
            if "BackgroundSuppression" not in tag_json and "BackgroundSuppressionNumberPulses" in tag_json:
                try:
                    tag_json["BackgroundSuppression"] = float(tag_json["BackgroundSuppressionNumberPulses"]) > 0
                except (TypeError, ValueError):
                    pass
            if "BackgroundSuppression" not in tag_json:
                print("WARNING: BackgroundSuppression could not be inferred from the available DICOM/JSON for", name)
            with open(os.path.join(derivatives, name + ".json"), "w") as f:
                json.dump(tag_json, f, indent=2)

        # Each 3D frame alternates between control and label.
        # The first kind is determined from acquisition time above.
        count = int(subprocess.check_output(["fslval", os.path.join(derivatives, name), "dim4"]).decode().strip())
        context_name = "sub-" + subject + "_" + session + "_aslcontext.tsv"
        with open(os.path.join(derivatives, context_name), "w") as context:
            context.write("volume_type\n")
            for i in range(count):
                context.write(("control" if (i % 2 == 0) == ctrl_first else "label") + "\n")

        # Convert the closest M0 series from this scan, if present.
        if series["m0"]:
            m0 = series["m0"].pop(0)
            m0_name = "sub-" + subject + "_" + session + "_m0scan"
            convert(m0["folder"], derivatives, m0_name)
            m0_json_path = os.path.join(derivatives, m0_name + ".json")
            if os.path.exists(m0_json_path):
                with open(m0_json_path) as f:
                    m0_json = json.load(f)
                m0_json["IntendedFor"] = "bids::sub-" + subject + "/" + session + "/perf/" + name + ".nii.gz"
                with open(m0_json_path, "w") as f:
                    json.dump(m0_json, f, indent=2)

        print("Created", derivatives)

    # T1w/MPRAGE is optional. Put it under each PLD folder created above.
    for t1w in series["t1w"]:
        for ctrl in series["ctrl"]:
            session = "ses-PLD" + ctrl["pld"]
            anat = os.path.join(output_folder, session, "anat")
            os.makedirs(anat, exist_ok=True)
            convert(t1w["folder"], anat, "sub-" + subject + "_" + session + "_T1w")


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

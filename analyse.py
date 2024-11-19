import os
from time import sleep
import subprocess
import re
import yaml
from datetime import datetime
from prettytable import PrettyTable
import math

NUMBER_OF_INIT_CONTAINERS = 3

def check_image_pull_substring(input_string):
    # Define the regex pattern
    pattern = r'Successfully pulled image "([^"]+)" in ([\d\.]+(?:ms|s)) \(([\d\.]+(?:ms|s) including waiting)\)'

    # Match the pattern
    match = re.search(pattern, input_string)

    if match:
        # Extract groups for demonstration (image name, timestamp_A, timestamp_B)
        image_name = match.group(1)
        timestamp_a = match.group(2)
        timestamp_b = match.group(3)
        return {
            "matched": True,
            "image_name": image_name,
            "timestamp_A": timestamp_a,
            "timestamp_B": timestamp_b
        }
    else:
        return {"matched": False}

def extract_and_display_init_container_data(yaml_content, image_pull_durations):
    # Load the YAML content into a Python dictionary
    data = yaml.safe_load(yaml_content)

    # Extract the pod startTime
    pod_start_time = data.get("status", {}).get("startTime", "N/A")

    # Navigate to the initContainerStatuses in the status section
    init_container_statuses = data.get("status", {}).get("initContainerStatuses", [])

    # Print the pod start time
    print(f"Pod Start Time: {pod_start_time}")
    print()

    # Create a table to display the results
    table = PrettyTable()
    table.field_names = ["Container Name", "Start Time", "Finish Time", "Duration (seconds)", "Total Duration (seconds)", "Total Duration Using Formula (seconds)",  "Relative Error (%)"]

    previous_finish_time = None  # To store the previous container's finish time
    sum_total_duration = 0  # Sum of actual total durations
    sum_formula_duration = 0  # Sum of total durations using formula


    for index, container in enumerate(init_container_statuses):
        image = container.get("image", "unknown").replace(":latest", "")
        name = container.get("name", "unknown")
        started_at = container.get("state", {}).get("terminated", {}).get("startedAt", "N/A")
        finished_at = container.get("state", {}).get("terminated", {}).get("finishedAt", "N/A")

        # Calculate duration in seconds
        if started_at != "N/A" and finished_at != "N/A":
            start_time = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            finish_time = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            duration = (finish_time - start_time).total_seconds()
        else:
            duration = "N/A"

        # Calculate total duration (rounded imagePullDuration + duration)
        image_pull_duration_ms = str(image_pull_durations.get(image, 0))  # Default to 0 if not found
        if image_pull_duration_ms != "0":
            if image_pull_duration_ms.endswith("ms"):
                image_pull_duration_ms = float(image_pull_duration_ms[:-2])
            else:
                image_pull_duration_ms = float(image_pull_duration_ms[:-1])*1000
        image_pull_duration_seconds = math.ceil(image_pull_duration_ms / 1000)  # Round up to the nearest second
        total_duration = (image_pull_duration_seconds + duration) if duration != "N/A" else "N/A"

        # Calculate total duration using the formula
        if index == 0:  # First init container
            if pod_start_time != "N/A" and finished_at != "N/A":
                pod_start_time_dt = datetime.fromisoformat(pod_start_time.replace("Z", "+00:00"))
                total_duration_using_formula = (finish_time - pod_start_time_dt).total_seconds()
        else:  # Subsequent containers
            if finished_at != "N/A" and previous_finish_time is not None:
                previous_finish_time_dt = datetime.fromisoformat(previous_finish_time.replace("Z", "+00:00"))
                total_duration_using_formula = (finish_time - previous_finish_time_dt).total_seconds()

        # Calculate relative error between total duration and total duration using formula
        if total_duration != "N/A" and total_duration_using_formula != "N/A":
            relative_error = abs(total_duration - total_duration_using_formula) / total_duration * 100
        else:
            relative_error = "N/A"


        # Add row to the table
        table.add_row([name, started_at, finished_at, duration, total_duration, total_duration_using_formula, relative_error])

        # Sum the actual total durations and the durations using the formula
        if total_duration != "N/A" and total_duration_using_formula != "N/A":
            sum_total_duration += total_duration
            sum_formula_duration += total_duration_using_formula

        # Store the current container's finish time for the next iteration
        previous_finish_time = finished_at

    # Print the table
    print(table)

    # Calculate total relative error
    if sum_formula_duration != 0:
        total_relative_error = abs(sum_total_duration - sum_formula_duration) / sum_total_duration * 100
    else:
        total_relative_error = "N/A"
    total_relative_error = str(total_relative_error)
    if len(total_relative_error) > 5:
        total_relative_error = total_relative_error[:5]

    print(f"\nTotal Relative Error: {total_relative_error if total_relative_error != 'N/A' else 'N/A'} %")

# delete pod if it already exists
os.system("kubectl delete pod sample-pod")

# create pod again
os.system("kubectl apply -f sample-pod.yaml")


# wait until the pod becomes in the read state
is_running = False
while not is_running:
    output = subprocess.run(['kubectl', 'get' ,'pod', 'sample-pod'], stdout=subprocess.PIPE)
    is_running = "Running" in str(output.stdout)
    print("waiting for pod to become in Running state...")
    sleep(5)

# Generate pod describe and extract image pull time for each init container
pod_describe = subprocess.run(['kubectl', 'describe', 'pod', 'sample-pod'], stdout=subprocess.PIPE).stdout.decode('ascii').split('\n')
idx = 0
initContainersImagePullTimes = {}
while idx < len(pod_describe):
    if "Events" in pod_describe[idx]:
        print("Parsing events...")
        idx+=1
        while idx < len(pod_describe) and len(initContainersImagePullTimes) < NUMBER_OF_INIT_CONTAINERS:
            line = pod_describe[idx]
            match_line = check_image_pull_substring(line.strip())
            if match_line["matched"]:
                initContainersImagePullTimes[match_line["image_name"]] = match_line["timestamp_A"]
            idx+=1
        break
    idx+=1

print("==== Image Pull Times =====")
for image, time in initContainersImagePullTimes.items():
    print(image, " ", time)

print()
print("Parsing InitContainerStatuses ...")

# Get pod manifest and extract finishedAt and startedAt properties of init containers
pod_get = subprocess.run(['kubectl', 'get', 'pod', 'sample-pod', '-o', 'yaml'], stdout=subprocess.PIPE).stdout.decode('ascii')
start_and_finish_times = extract_and_display_init_container_data(pod_get, initContainersImagePullTimes)



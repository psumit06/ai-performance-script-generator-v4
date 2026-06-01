import subprocess

result = subprocess.run(

    [
        r"C:\apache-jmeter-5.3\bin\jmeter.bat",
        "-v"
    ],

    capture_output=True,

    text=True,

    shell=True
)

print(result.stdout)

print(result.stderr)
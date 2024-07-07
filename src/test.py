from abaqus2py import AbaqusSimulator
from abaqus2py import create_preprocess_script

simulator = AbaqusSimulator()

create_preprocess_script(working_dir,python_file,function_name)
print("End")
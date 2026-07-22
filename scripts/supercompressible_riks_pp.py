"""
Created on 2020-09-22 16:07:04
Last modified on 2020-09-23 07:10:39

@author: L. F. Pereira (lfpereira@fe.up.pt))
"""

import pickle

import numpy as np

# imports
from abaqus import session  # NOQA

# # variable initialization and odb opening
# job_name = 'Simul_SUPERCOMPRESSIBLE_RIKS'
# odb_name = '{}.odb'.format(job_name)
# odb = session.openOdb(name=odb_name)


def main(odb):
    # variable initialization and odb opening
    # odb_name = '{}.odb'.format(job_name)
    # odb = session.openOdb(name=odb_name)

    riks_results = {}

    # reference point data
    variables = ["U", "UR", "RF", "RM"]
    set_name = "ZTOP_REF_POINT"
    step_name = "RIKS_STEP"
    step = odb.steps[step_name]
    directions = (1, 2, 3)
    nodes = odb.rootAssembly.nodeSets[set_name].nodes[0]
    # get variables
    for variable in variables:
        y = []
        for node in nodes:
            instance_name = (
                node.instanceName if node.instanceName else "ASSEMBLY"
            )
            name = "Node " + instance_name + "." + str(node.label)
            historyOutputs = step.historyRegions[name].historyOutputs
            node_data = []
            for direction in directions:
                node_data.append(
                    [
                        data[1]
                        for data in historyOutputs[
                            "%s%i" % (variable, direction)
                        ].data
                    ]
                )
            y.append(node_data)
        riks_results[variable] = np.array(y[0])

    # maximum absolute strain over the model (E field output, components
    # E11/E33 as in the original get_results), reduced to a single scalar:
    # the full E field would add tens of MB per design, while only the max
    # is needed to upgrade the coilable label to class 2 downstream. The
    # per-frame guard makes odbs without an E field (the request comes
    # from the element-type-dependent PRESELECT defaults) simply skip the
    # key, in which case the downstream label stays binary.
    directions = (1, 3)
    element_set = odb.rootAssembly.elementSets[" ALL ELEMENTS"]
    e_max = None
    for frame in step.frames:
        if "E" not in frame.fieldOutputs.keys():
            continue
        outputs = frame.fieldOutputs["E"].getSubset(region=element_set).values
        for output in outputs:
            for direction in directions:
                value = abs(output.data[direction - 1])
                if e_max is None or value > e_max:
                    e_max = value
    if e_max is not None:
        riks_results["E_max"] = float(e_max)

    with open("results.pkl", "wb") as file:
        pickle.dump(riks_results, file)

import json, os
from jupyter_client.kernelspec import install_kernel_spec

def main():
    here = os.path.dirname(__file__)
    with open(os.path.join(here, 'kernel.json')) as f:
        spec = json.load(f)
    install_kernel_spec(os.path.join(here, 'kernel.json'),
                        kernel_name='evolver', user=True)



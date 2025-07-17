from ipykernel.kernelapp import IPKernelApp
from .kernel import EvolverKernel  # ajusta a tu nombre real

def main():
    IPKernelApp.launch_instance(kernel_class=EvolverKernel)

if __name__ == "__main__":
    main()

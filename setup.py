from setuptools import setup

setup(
    name='evolver_kernel',
    version='0.1',
    packages=['evolver_kernel'],
    install_requires=['metakernel'],
    entry_points={
        'console_scripts': [
            'install_evolver_kernel = evolver_kernel.install:main'
        ]
    }
)

"""Setup for mermaid2drawio package."""

from setuptools import setup, find_packages

setup(
    name="mermaid2drawio",
    version="1.0.0",
    description="Scan Git repos for Mermaid diagrams and convert to Draw.io with cloud service icons",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="mermaid2drawio",
    python_requires=">=3.10",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "mermaid2drawio=mermaid2drawio.cli:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Documentation",
    ],
)

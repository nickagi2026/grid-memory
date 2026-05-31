from setuptools import setup, find_packages

with open("README.md") as f:
    long_description = f.read()

setup(
    name="grid-memory",
    version="1.2.2",
    description="Grid Memory — shared persistent memory for multi-agent teams",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="MIKE / Nick",
    author_email="mike@openclaw.ai",
    url="https://github.com/openclaw/grid-memory",
    packages=find_packages(exclude=[
        'grid_memory.enterprise', 'grid_memory.enterprise.*',
        'grid_memory.hooks', 'grid_memory.hooks.*',
        'grid_memory.product', 'grid_memory.product.*',
        'grid_memory.intel.decision_dna', 'grid_memory.intel.digital_twin',
        'grid_memory.intel.failure_predictor', 'grid_memory.intel.gps',
        'grid_memory.intel.learning_engine', 'grid_memory.intel.radar2',
        'grid_memory.intel.readiness', 'grid_memory.intel.reality',
    ]),
    python_requires=">=3.8",
    install_requires=[],
    entry_points={
        "console_scripts": [
            "grid=grid_memory.cli:main",
        ],
    },
    extras_require={
        "dev": ["pytest"],
        "autogen": ["pyautogen>=0.2"],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific Computing :: Artificial Intelligence",
        "Topic :: System :: Distributed Computing",
    ],
    keywords="multi-agent, shared-memory, agent-memory, ai-agents, crewai, autogen, langgraph",
)

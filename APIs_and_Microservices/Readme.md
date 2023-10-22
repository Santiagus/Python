# APIs and Microservices

This folder contains instructions to create APIs and Microservices.

Each subfolder contains an example and the instructions to reproduce it from scratch are place in a containt ***Readme.md*** file.

Number prefix per folder indicate increasing complexity or size.

Main target it is to reduce verbosity to the minimum and learn by practising.

## Definitions
***Microservice*** : architectural style in which components of a system are designed as independently deployable services.

***API (Application Programming Interface)***:

An API is a set of rules and protocols that allows different software applications to communicate with each other. It defines the methods and data formats that applications can use to request and exchange information, enabling them to work together and share data.

***REST API (Representational State Transfer API)***:

REST is an architectural style for designing networked applications. A REST API is a type of API that follows the principles of REST. It uses standard HTTP methods (GET, POST, PUT, DELETE, etc.) to perform operations on resources represented as URLs. It relies on stateless communication and uses standard status codes to indicate the outcome of requests. REST APIs are often used for web services and are known for their simplicity and scalability.

***GraphQL API***:

GraphQL is a query language and runtime for APIs that was developed by Facebook. A GraphQL API allows clients to request only the data they need and nothing more. 

Unlike REST APIs, where the server determines the shape of the response, GraphQL APIs enable clients to specify the structure of the response in their queries. 

This flexibility makes GraphQL a powerful tool for fetching and manipulating data, especially in scenarios where the client's requirements may vary.

***Summary*** :

APIs provide a way for software components to interact, and REST and GraphQL are two common approaches for building APIs, each with its own characteristics and best use cases.

## Repository Structure

Example:
```
.
├── 00_My_Project
│   ├── Readme.md
│   └── requirements.txt
└── Readme.md
```

- *Readme.md* : Describes steps to replicate the project.

- *requirements*: Project's required packages
    
    

## Setup: 

1. Create a virtual environment per project \
```python -m venv .venv```

2. Install required packages: \
``` pip install -r requirements```

3. Follow steps in `Readme.md` file




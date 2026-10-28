CREATE DATABASE VehicleRentalDB;

USE VehicleRentalDB;

CREATE TABLE LOCATION (
    LocationID INT PRIMARY KEY,
    Name VARCHAR(100),
    Address VARCHAR(200),
    City VARCHAR(50),
    State VARCHAR(50),
    ZipCode VARCHAR(10)
);

CREATE TABLE STAFF (
    StaffID INT PRIMARY KEY,
    FirstName VARCHAR(50),
    LastName VARCHAR(50),
    Role VARCHAR(50),
    Email VARCHAR(100),
    HireDate DATE,
    ContactInfo VARCHAR(100),
    Phone VARCHAR(15),
    LocationID INT,
    FOREIGN KEY (LocationID) REFERENCES LOCATION(LocationID)
);

CREATE TABLE CUSTOMER (
    CustomerID INT PRIMARY KEY,
    FirstName VARCHAR(50),
    LastName VARCHAR(50),
    Email VARCHAR(100),
    Phone VARCHAR(15),
    Address VARCHAR(200),
    LicenseNumber VARCHAR(50),
    DateOfBirth DATE
);

CREATE TABLE DRIVERS_LICENSE (
    LicenseID INT PRIMARY KEY,
    Country VARCHAR(50),
    ExpiryDate DATE
);

CREATE TABLE VEHICLE (
    VehicleID INT PRIMARY KEY,
    Make VARCHAR(50),
    Model VARCHAR(50),
    Type VARCHAR(50),
    Year INT,
    Color VARCHAR(30),
    FuelType VARCHAR(30),
    PlateNumber VARCHAR(20) UNIQUE,
    HourlyRate DECIMAL(10,2),
    Status VARCHAR(30)
);

CREATE TABLE RENTAL (
    RentalID INT PRIMARY KEY,
    StartDate DATE,
    EndDate DATE,
    PickupLocationID INT,
    ReturnLocationID INT,
    TotalCost DECIMAL(10,2),
    PaymentStatus VARCHAR(30),
    FuelLevelStart DECIMAL(5,2),
    FuelLevelEnd DECIMAL(5,2),
    CustomerID INT,
    VehicleID INT,
    StaffID INT,
    FOREIGN KEY (PickupLocationID) REFERENCES LOCATION(LocationID),
    FOREIGN KEY (ReturnLocationID) REFERENCES LOCATION(LocationID),
    FOREIGN KEY (CustomerID) REFERENCES CUSTOMER(CustomerID),
    FOREIGN KEY (VehicleID) REFERENCES VEHICLE(VehicleID),
    FOREIGN KEY (StaffID) REFERENCES STAFF(StaffID)
);

CREATE TABLE MAINTENANCE (
    MaintenanceID INT PRIMARY KEY,
    Date DATE,
    Description VARCHAR(200),
    Cost DECIMAL(10,2),
    StaffID INT,
    Status VARCHAR(30),
    VehicleID INT,
    FOREIGN KEY (StaffID) REFERENCES STAFF(StaffID),
    FOREIGN KEY (VehicleID) REFERENCES VEHICLE(VehicleID)
);

CREATE TABLE INSURANCE (
    InsuranceID INT PRIMARY KEY,
    Provider VARCHAR(100),
    PolicyNumber VARCHAR(50),
    CoverageStart DATE,
    CoverageEnd DATE,
    MaintenanceID INT UNIQUE,
    FOREIGN KEY (MaintenanceID) REFERENCES MAINTENANCE(MaintenanceID)
);

INSERT INTO LOCATION VALUES
(1, 'Main Branch', 'Park Street', 'Kolkata', 'West Bengal', '700016'),
(2, 'Airport Branch', 'Airport Road', 'Kolkata', 'West Bengal', '700052'),
(3, 'New Town Branch', 'Action Area 1', 'Kolkata', 'West Bengal', '700156');

INSERT INTO STAFF VALUES
(101, 'Rahul', 'Sharma', 'Agent', 'rahul@gmail.com',
 '2024-01-15', 'Office', '9876543210', 1),
(102, 'Amit', 'Roy', 'Mechanic', 'amit@gmail.com',
 '2023-06-10', 'Workshop', '9876543211', 2),
(103, 'Sourav', 'Das', 'Agent', 'sourav@gmail.com',
 '2024-03-20', 'Office', '9876543212', 3);

INSERT INTO CUSTOMER VALUES
(201, 'Arjun', 'Kumar', 'arjun@gmail.com', '9876500001',
 'Kolkata, West Bengal', 'DL12345', '2003-05-10'),
(202, 'Rohan', 'Singh', 'rohan@gmail.com', '9876500002',
 'Howrah, West Bengal', 'DL12346', '2002-08-15'),
(203, 'Ankit', 'Das', 'ankit@gmail.com', '9876500003',
 'Siliguri, West Bengal', 'DL12347', '2004-01-20');

INSERT INTO DRIVERS_LICENSE VALUES
(301, 'India', '2028-05-10'),
(302, 'India', '2027-08-15'),
(303, 'India', '2029-01-20');

INSERT INTO VEHICLE VALUES
(401, 'Toyota', 'Innova', 'SUV', 2023, 'White', 'Diesel',
 'WB01AB1234', 250.00, 'Available'),
(402, 'Honda', 'City', 'Sedan', 2022, 'Black', 'Petrol',
 'WB02CD5678', 200.00, 'Rented'),
(403, 'Bajaj', 'Pulsar N160', 'Bike', 2024, 'Blue', 'Petrol',
 'WB03EF9012', 80.00, 'Available');

INSERT INTO RENTAL VALUES
(501, '2026-10-01', '2026-10-03', 1, 1, 1200.00,
 'Paid', 90.00, 70.00, 201, 401, 101),
(502, '2026-10-02', '2026-10-04', 2, 3, 1600.00,
 'Pending', 95.00, 75.00, 202, 402, 103);

INSERT INTO MAINTENANCE VALUES
(601, '2026-09-20', 'Engine servicing', 5000.00,
 102, 'Completed', 401),
(602, '2026-09-25', 'Oil change', 1500.00,
 102, 'Completed', 403);

INSERT INTO INSURANCE VALUES
(701, 'ICICI Lombard', 'POL10001',
 '2026-01-01', '2027-01-01', 601),
(702, 'HDFC ERGO', 'POL10002',
 '2026-02-01', '2027-02-01', 602);
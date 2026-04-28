/* =========================================================
   File Name   : employee_certification.sql
   Purpose     : Sample SQL code for certification
   Author      : <Your Name>
   Created On  : 24-Apr-2026
   Database    : SQL Server
========================================================= */

-- ============================
-- 1. Create Table
-- ============================
IF OBJECT_ID('dbo.Employees', 'U') IS NOT NULL
    DROP TABLE dbo.Employees;
GO

CREATE TABLE dbo.Employees
(
    EmployeeID     INT IDENTITY(1,1) PRIMARY KEY,
    FirstName      VARCHAR(50)  NOT NULL,
    LastName       VARCHAR(50)  NOT NULL,
    Email          VARCHAR(100) UNIQUE,
    Salary         DECIMAL(10,2) CHECK (Salary >= 0),
    Department     VARCHAR(50),
    CreatedDate    DATETIME DEFAULT GETDATE()
);
GO

-- ============================
-- 2. Insert Sample Data
-- ============================
INSERT INTO dbo.Employees (FirstName, LastName, Email, Salary, Department)
VALUES
('Harish', 'Billa', 'harish@example.com', 75000, 'IT'),
('Anita', 'Sharma', 'anita@example.com', 65000, 'HR'),
('Rahul', 'Verma', 'rahul@example.com', 80000, 'Finance');
GO

-- ============================
-- 3. Stored Procedure
-- ============================
IF OBJECT_ID('dbo.sp_AddEmployee', 'P') IS NOT NULL
    DROP PROCEDURE dbo.sp_AddEmployee;
GO

CREATE PROCEDURE dbo.sp_AddEmployee
(
    @FirstName   VARCHAR(50),
    @LastName    VARCHAR(50),
    @Email       VARCHAR(100),
    @Salary      DECIMAL(10,2),
    @Department  VARCHAR(50)
)
AS
BEGIN
    SET NOCOUNT ON;

    BEGIN TRY
        -- Validation
        IF @Salary < 0
        BEGIN
            RAISERROR ('Salary cannot be negative', 16, 1);
            RETURN;
        END

        INSERT INTO dbo.Employees
        (
            FirstName,
            LastName,
            Email,
            Salary,
            Department
        )
        VALUES
        (
            @FirstName,
            @LastName,
            @Email,
            @Salary,
            @Department
        );

        PRINT 'Employee inserted successfully';
    END TRY
    BEGIN CATCH
        PRINT 'Error occurred';
        PRINT ERROR_MESSAGE();
    END CATCH
END;
GO

-- ============================
-- 4. Execute Stored Procedure
-- ============================
EXEC dbo.sp_AddEmployee
    @FirstName  = 'Suresh',
    @LastName   = 'Kumar',
    @Email      = 'suresh@example.com',
    @Salary     = 72000,
    @Department = 'IT';
GO

-- ============================
-- 5. Verify Results
-- ============================
SELECT * FROM dbo.Employees;
GO

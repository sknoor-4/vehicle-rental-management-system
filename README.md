# Roadly Vehicle Rental Portal

One Flask website with two separate experiences: a customer booking portal at `/` and a protected fleet dashboard at `/admin`. It uses the provided `VehicleRentalDB` schema and its original table/column terminology.

## Start the app

1. Start MySQL Server.
2. Run the existing `vehicle_rental.sql` file from `~/vehicle rental management system DBMS/` in MySQL Workbench or the MySQL command line. It creates the `VehicleRentalDB` database and sample data.
3. In Terminal, open this project folder and install dependencies:

   ```bash
   python3 -m pip install -r requirements.txt
   ```

4. Start the server with `python3 app.py`, then open http://127.0.0.1:5000. If another local app is already using port 5000, use `PORT=5001 python3 app.py` and open http://127.0.0.1:5001.

The MySQL connection is `localhost`, user `root`, password `MyNewPass@123`, database `VehicleRentalDB`.

## Customer portal

Customers can create an account, browse available vehicles, request a booking with pickup and return dates, see their rental history, and cancel upcoming unpaid rentals. Registration and every booking are checked on the server for a minimum age of 18, and bookings require a driving-license number. On first account use, the app creates a separate `CUSTOMER_ACCOUNT` table for password hashes; the supplied SQL schema remains unchanged. Bookings use the first configured location and first staff member whose role is `Agent`.

Vehicles marked `Rented` remain visible in the customer catalog with an expected return and estimated next availability (the day after the rental end date). These dates are estimates until the admin confirms the vehicle has been checked back in. In the admin dashboard, click **Available now**, **Rented out**, or **Pending payments** to open each action list. Mark a payment paid only after confirming receipt through the actual bank/payment provider. A manager can keep a car marked rented or mark it returned after check-in. Customer records can be updated and online booking access can be paused/restored without deleting rental history.

Before a vehicle can be booked, an administrator must save that vehicle's verified insurer, policy number, coverage dates, coverage limit, and customer excess/deductible. The booking is rejected if the policy does not cover the complete requested rental period. The customer portal displays those values and policy notes. Final accident liability depends on the real policy wording, exclusions, insurer's claim decision, and documented repair costs; the site does not invent or promise a final charge. Add the amounts from the actual insurance documents and get the rental terms reviewed for the business's jurisdiction.

## Admin portal

Open `/admin` to be redirected to the admin sign-in. Local defaults are username `admin` and password `admin123`. Before sharing the site, set `ROADLY_ADMIN_USER`, `ROADLY_ADMIN_PASSWORD`, and `FLASK_SECRET_KEY` environment variables to private values. The admin can add vehicles, protect linked vehicle history during deletion, configure each vehicle's insurance, add maintenance records assigned to a mechanic, manage customer booking access, review and assign customer mechanic requests, manage service status and vehicle availability, update rental payment status, and review full rental details.

The **Need help?** widget currently uses a local rules-based support assistant for availability, bookings, payments, insurance, and service requests. It does not send customer messages off this device. A generative AI connection needs explicit approval before customer-entered chat text can be sent to OpenAI for a response. Mechanic requests are saved for admin follow-up; they do not dispatch a mechanic or confirm a visit automatically.

Vehicle and customer IDs are generated from each table's current maximum because the supplied schema uses manually assigned primary keys.

To replace a vehicle photo, sign in to `/admin`, choose a JPG, PNG, or WEBP file in that vehicle card's photo field, then select **Upload photo**. Files up to 8 MB are stored under `static/uploads/`; the selected image is shared by the customer catalog and admin dashboard through the separate `VEHICLE_IMAGE` table. Use **Full details** beside a rental in the Recent rentals section to see customer contact, vehicle details, dates, amount, payment, pickup/return locations, staff, and recorded fuel levels.

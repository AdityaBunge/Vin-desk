const express = require("express");

const db = require("../config/db");

const authenticateToken =
    require("../middleware/authMiddleware");

const router = express.Router();


// =====================================================
// GET ALL VEHICLES
// =====================================================

router.get("/", authenticateToken, async (req, res) => {

    try {

        const [vehicles] = await db.promise().query(
            `SELECT *
             FROM vehicles
             ORDER BY created_at DESC`
        );

        res.json({
            success: true,
            count: vehicles.length,
            vehicles: vehicles
        });

    } catch (error) {

        console.error("Get vehicles error:", error);

        res.status(500).json({
            success: false,
            message: "Failed to fetch vehicles"
        });

    }

});


// =====================================================
// GET VEHICLE BY ID
// =====================================================

router.get("/:id", authenticateToken, async (req, res) => {

    try {

        const { id } = req.params;

        const [vehicles] = await db.promise().query(
            `SELECT *
             FROM vehicles
             WHERE id = ?`,
            [id]
        );

        if (vehicles.length === 0) {

            return res.status(404).json({
                success: false,
                message: "Vehicle not found"
            });

        }

        res.json({
            success: true,
            vehicle: vehicles[0]
        });

    } catch (error) {

        console.error("Get vehicle error:", error);

        res.status(500).json({
            success: false,
            message: "Failed to fetch vehicle"
        });

    }

});


// =====================================================
// SEARCH VEHICLE BY VIN OR REGISTRATION NUMBER
// =====================================================

router.get(
    "/search/:identifier",
    authenticateToken,
    async (req, res) => {

        try {

            const { identifier } = req.params;

            const [vehicles] = await db.promise().query(
                `SELECT
                    v.*,

                    c.name AS customer_name,
                    c.email AS customer_email,
                    c.phone AS customer_phone,

                    s.sale_price,
                    s.sale_date,
                    s.payment_method

                FROM vehicles v

                LEFT JOIN sales s
                    ON v.id = s.vehicle_id

                LEFT JOIN customers c
                    ON s.customer_id = c.id

                WHERE
                    v.vin = ?
                    OR v.registration_number = ?`,
                [
                    identifier,
                    identifier
                ]
            );


            if (vehicles.length === 0) {

                return res.status(404).json({
                    success: false,
                    message: "Vehicle not found"
                });

            }


            res.json({
                success: true,
                vehicle: vehicles[0]
            });


        } catch (error) {

            console.error("Vehicle search error:", error);

            res.status(500).json({
                success: false,
                message: "Vehicle search failed"
            });

        }

    }
);


// =====================================================
// ADD VEHICLE
// =====================================================

router.post("/", authenticateToken, async (req, res) => {

    try {

        const {
            vin,
            registration_number,
            brand,
            model,
            vehicle_type,
            manufacturing_year,
            color,
            price,
            status
        } = req.body;


        if (!vin || !brand || !model) {

            return res.status(400).json({
                success: false,
                message: "VIN, brand and model are required"
            });

        }


        const [existingVehicle] = await db.promise().query(
            `SELECT id
             FROM vehicles
             WHERE vin = ?
                OR registration_number = ?`,
            [
                vin,
                registration_number
            ]
        );


        if (existingVehicle.length > 0) {

            return res.status(400).json({
                success: false,
                message: "Vehicle with this VIN or registration number already exists"
            });

        }


        const [result] = await db.promise().query(
            `INSERT INTO vehicles
            (
                vin,
                registration_number,
                brand,
                model,
                vehicle_type,
                manufacturing_year,
                color,
                price,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
            [
                vin,
                registration_number,
                brand,
                model,
                vehicle_type,
                manufacturing_year,
                color,
                price,
                status || "available"
            ]
        );


        res.status(201).json({

            success: true,

            message: "Vehicle added successfully",

            vehicleId: result.insertId

        });


    } catch (error) {

        console.error("Add vehicle error:", error);

        res.status(500).json({
            success: false,
            message: "Failed to add vehicle"
        });

    }

});


module.exports = router;
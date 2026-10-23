const express = require("express");
const bcrypt = require("bcryptjs");
const jwt = require("jsonwebtoken");

const db = require("../config/db");

const router = express.Router();


// ===============================
// REGISTER USER
// ===============================
router.post("/register", async (req, res) => {

    try {

        const {
            name,
            email,
            password,
            role
        } = req.body;


        // Check required fields
        if (!name || !email || !password) {

            return res.status(400).json({
                success: false,
                message: "Name, email and password are required"
            });

        }


        // Check whether email already exists
        const [existingUsers] = await db.promise().query(
            "SELECT id FROM users WHERE email = ?",
            [email]
        );


        if (existingUsers.length > 0) {

            return res.status(400).json({
                success: false,
                message: "Email already registered"
            });

        }


        // Hash password
        const hashedPassword = await bcrypt.hash(
            password,
            10
        );


        // Insert user
        const [result] = await db.promise().query(
            `INSERT INTO users
            (name, email, password, role)
            VALUES (?, ?, ?, ?)`,
            [
                name,
                email,
                hashedPassword,
                role || "sales"
            ]
        );


        res.status(201).json({

            success: true,

            message: "User registered successfully",

            userId: result.insertId

        });


    } catch (error) {

        console.error("Register error:", error);

        res.status(500).json({

            success: false,

            message: "Server error"

        });

    }

});


// ===============================
// LOGIN USER
// ===============================
router.post("/login", async (req, res) => {

    try {

        const {
            email,
            password
        } = req.body;


        // Validate input
        if (!email || !password) {

            return res.status(400).json({

                success: false,

                message: "Email and password are required"

            });

        }


        // Find user
        const [users] = await db.promise().query(
            "SELECT * FROM users WHERE email = ?",
            [email]
        );


        if (users.length === 0) {

            return res.status(401).json({

                success: false,

                message: "Invalid email or password"

            });

        }


        const user = users[0];


        // Compare password
        const passwordMatch = await bcrypt.compare(
            password,
            user.password
        );


        if (!passwordMatch) {

            return res.status(401).json({

                success: false,

                message: "Invalid email or password"

            });

        }


        // Create JWT
        const token = jwt.sign(

            {
                id: user.id,
                role: user.role
            },

            process.env.JWT_SECRET,

            {
                expiresIn: "1d"
            }

        );


        // Send response
        res.json({

            success: true,

            message: "Login successful",

            token,

            user: {

                id: user.id,

                name: user.name,

                email: user.email,

                role: user.role

            }

        });


    } catch (error) {

        console.error("Login error:", error);

        res.status(500).json({

            success: false,

            message: "Server error"

        });

    }

});


module.exports = router;
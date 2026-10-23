require("dotenv").config();

const express = require("express");
const cors = require("cors");

const db = require("./config/db");

const authRoutes = require("./routes/authRoutes");
const vehicleRoutes = require("./routes/vehicleRoutes");

const app = express();

app.use(cors());
app.use(express.json());


// Authentication routes
app.use("/api/auth", authRoutes);

// Vehicle routes
app.use("/api/vehicles", vehicleRoutes);


app.get("/", (req, res) => {
    res.json({
        message: "VinDesk API is running successfully"
    });
});


app.get("/api/test-db", async (req, res) => {
    try {
        const [rows] = await db.promise().query(
            "SELECT 1 AS result"
        );

        res.json({
            success: true,
            message: "Database connection is working",
            data: rows
        });

    } catch (error) {
        console.error(error);

        res.status(500).json({
            success: false,
            message: "Database connection failed",
            error: error.message
        });
    }
});


const PORT = process.env.PORT || 5000;

app.listen(PORT, () => {
    console.log(
        `🚀 VinDesk backend running at http://localhost:${PORT}`
    );
});
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import "./Vehicles.css";

function Vehicles() {
  const navigate = useNavigate();

  const [search, setSearch] = useState("");
  const [vehicle, setVehicle] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const searchVehicle = async (e) => {
    e.preventDefault();

    if (!search.trim()) {
      setMessage("Please enter a VIN or registration number.");
      setVehicle(null);
      return;
    }

    setLoading(true);
    setMessage("");
    setVehicle(null);

    try {
      const token = localStorage.getItem("token");

      const response = await fetch(
        `http://localhost:5000/api/vehicles/search/${encodeURIComponent(
          search.trim()
        )}`,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      const data = await response.json();

      if (!response.ok) {
        setMessage(data.message || "Vehicle not found.");
        return;
      }

      setVehicle(data.data || data.vehicle || data);
    } catch (error) {
      console.error(error);
      setMessage("Unable to connect to the VinDesk server.");
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    navigate("/");
  };

  return (
    <div className="vehicles-page">

      <aside className="sidebar">

        <div className="brand">
          <div className="brand-logo">VD</div>

          <div>
            <h2>VinDesk</h2>
            <span>Dealership System</span>
          </div>
        </div>

        <nav className="navigation">

          <button
            className="nav-item"
            onClick={() => navigate("/dashboard")}
          >
            🏠 Dashboard
          </button>

          <button className="nav-item active">
            🚗 Vehicles
          </button>

          <button className="nav-item">
            👥 Customers
          </button>

          <button className="nav-item">
            💰 Sales
          </button>

          <button className="nav-item">
            🔧 Service
          </button>

          <button className="nav-item">
            📊 Reports
          </button>

        </nav>

        <button
          className="logout-button"
          onClick={logout}
        >
          Logout
        </button>

      </aside>


      <main className="vehicles-main">

        <header className="vehicles-header">

          <div>
            <h1>Vehicles</h1>

            <p>
              Search and manage dealership vehicles
            </p>
          </div>

        </header>


        <section className="search-card">

          <h2>Search Vehicle</h2>

          <p>
            Search using VIN or registration number
          </p>

          <form
            className="search-form"
            onSubmit={searchVehicle}
          >

            <input
              type="text"
              placeholder="Enter VIN or registration number"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />

            <button
              type="submit"
              disabled={loading}
            >
              {loading ? "Searching..." : "Search"}
            </button>

          </form>

          {message && (
            <div className="message">
              {message}
            </div>
          )}

        </section>


        {vehicle && (

          <section className="vehicle-result">

            <div className="result-header">

              <div>
                <h2>Vehicle Details</h2>

                <p>
                  Vehicle found successfully
                </p>
              </div>

              <span className="status">
                Available
              </span>

            </div>


            <div className="vehicle-grid">

              <div className="vehicle-field">
                <span>VIN</span>
                <strong>{vehicle.vin || "-"}</strong>
              </div>

              <div className="vehicle-field">
                <span>Registration Number</span>
                <strong>
                  {vehicle.registration_number || "-"}
                </strong>
              </div>

              <div className="vehicle-field">
                <span>Brand</span>
                <strong>{vehicle.brand || "-"}</strong>
              </div>

              <div className="vehicle-field">
                <span>Model</span>
                <strong>{vehicle.model || "-"}</strong>
              </div>

              <div className="vehicle-field">
                <span>Vehicle Type</span>
                <strong>
                  {vehicle.vehicle_type || "-"}
                </strong>
              </div>

              <div className="vehicle-field">
                <span>Manufacturing Year</span>
                <strong>
                  {vehicle.manufacturing_year || "-"}
                </strong>
              </div>

              <div className="vehicle-field">
                <span>Color</span>
                <strong>{vehicle.color || "-"}</strong>
              </div>

              <div className="vehicle-field">
                <span>Price</span>
                <strong>
                  {vehicle.price
                    ? `₹${vehicle.price}`
                    : "-"}
                </strong>
              </div>

            </div>

          </section>

        )}

      </main>

    </div>
  );
}

export default Vehicles;
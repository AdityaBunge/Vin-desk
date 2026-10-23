import { useState } from "react";
import "./App.css";

function Login() {

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);


  const handleLogin = async (e) => {

    e.preventDefault();

    setMessage("");
    setLoading(true);

    try {

      const response = await fetch(
        "http://localhost:5000/api/auth/login",
        {
          method: "POST",

          headers: {
            "Content-Type": "application/json"
          },

          body: JSON.stringify({
            email,
            password
          })
        }
      );


      const data = await response.json();


      if (!response.ok) {

        setMessage(
          data.message || "Login failed"
        );

        setLoading(false);

        return;
      }


      localStorage.setItem(
        "token",
        data.token
      );


      localStorage.setItem(
        "user",
        JSON.stringify(data.user)
      );


      setMessage(
        `Welcome ${data.user.name}! Login successful.`
      );


      // Refresh the app so the router sees the new token
      window.location.href = "/dashboard";


    } catch (error) {

      console.error(error);

      setMessage(
        "Cannot connect to VinDesk server."
      );

    }

    setLoading(false);

  };


  return (

    <div className="login-page">

      <div className="login-card">

        <div className="logo-section">

          <div className="logo">
            VD
          </div>

          <h1>VinDesk</h1>

          <p>
            Vehicle Dealership Management System
          </p>

        </div>


        <form
          className="login-form"
          onSubmit={handleLogin}
        >

          <label>
            Email
          </label>

          <input
            type="email"
            placeholder="Enter your email"
            value={email}
            onChange={(e) =>
              setEmail(e.target.value)
            }
            required
          />


          <label>
            Password
          </label>

          <input
            type="password"
            placeholder="Enter your password"
            value={password}
            onChange={(e) =>
              setPassword(e.target.value)
            }
            required
          />


          <button
            type="submit"
            disabled={loading}
          >

            {loading
              ? "Signing in..."
              : "Sign In"}

          </button>


          {message && (

            <div className="message">
              {message}
            </div>

          )}

        </form>


        <div className="login-footer">

          <span>
            VinDesk
          </span>

          <span>
            © 2026
          </span>

        </div>

      </div>

    </div>

  );
}


export default Login;
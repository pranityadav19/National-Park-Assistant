import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        pine: "#0b3d2e",
        moss: "#7ea172",
        sand: "#f4efd8"
      }
    }
  },
  plugins: []
};

export default config;

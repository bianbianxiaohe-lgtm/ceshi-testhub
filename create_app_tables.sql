CREATE TABLE IF NOT EXISTS app_devices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    platform VARCHAR(20) NOT NULL,
    platform_version VARCHAR(50) DEFAULT '',
    device_type VARCHAR(20) DEFAULT 'real',
    udid VARCHAR(200) NOT NULL UNIQUE,
    appium_server_url VARCHAR(500) DEFAULT 'http://localhost:4723',
    status VARCHAR(20) DEFAULT 'offline',
    resolution VARCHAR(50) DEFAULT '',
    capabilities JSON,
    last_heartbeat DATETIME NULL,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS app_configs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    platform VARCHAR(20) NOT NULL,
    package_name VARCHAR(500) DEFAULT '',
    app_activity VARCHAR(500) DEFAULT '',
    app_path VARCHAR(500) DEFAULT '',
    project_id INT NULL,
    capabilities JSON,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 幂等：为 FeatureModule.versions 多对多字段创建中间表
-- Django 默认 M2M 表名: feature_modules_versions

CREATE TABLE IF NOT EXISTS feature_modules_versions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    featuremodule_id INT NOT NULL,
    version_id INT NOT NULL,
    UNIQUE KEY unique_fm_version (featuremodule_id, version_id),
    INDEX idx_fm_versions_featuremodule_id (featuremodule_id),
    INDEX idx_fm_versions_version_id (version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

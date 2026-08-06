SELECT COUNT(*) as total_associations FROM feature_modules_versions;
SELECT v.name as version_name, COUNT(fmv.featuremodule_id) as module_count
FROM versions v
JOIN versions_projects vp ON v.id = vp.version_id
JOIN feature_modules fm ON fm.project_id = vp.project_id
LEFT JOIN feature_modules_versions fmv ON fmv.featuremodule_id = fm.id AND fmv.version_id = v.id
GROUP BY v.id, v.name
ORDER BY v.name;

import { useState, useCallback, useMemo } from 'react';
import { getDefaultConfig, validateConfig, CONFIG_SCHEMA } from '../models/configModels';

export function useExperimentConfig(initialOverrides = {}) {
  const [config, setConfig] = useState(() => getDefaultConfig(initialOverrides));
  const [errors, setErrors] = useState({});

  const updateConfig = useCallback((key, value) => {
    if (!CONFIG_SCHEMA[key]) return;

    setConfig((prev) => {
      const next = { ...prev, [key]: value };

      Object.entries(CONFIG_SCHEMA).forEach(([otherKey, otherSchema]) => {
        if (otherSchema.visibleWhen && !otherSchema.visibleWhen(next)) {
          next[otherKey] = otherSchema.default;
        }
      });

      setErrors(validateConfig(next).errors);
      return next;
    });
  }, []);

  const isValid = useMemo(() => Object.keys(errors).length === 0, [errors]);

  // coerce form strings to the types the backend expects
  const getConfigForSubmit = useCallback(() => {
    const merged = { ...getDefaultConfig(initialOverrides), ...config };
    const result = {};
    Object.entries(merged).forEach(([key, value]) => {
      const schema = CONFIG_SCHEMA[key];
      if (!schema) return;
      if (schema.type === 'int') {
        result[key] = parseInt(value, 10);
      } else if (schema.type === 'float') {
        result[key] = parseFloat(value);
      } else if (schema.type === 'bool') {
        result[key] = Boolean(value);
      } else {
        result[key] = value;
      }
    });
    return result;
  }, [config, initialOverrides]);

  return { config, errors, isValid, updateConfig, getConfigForSubmit };
}

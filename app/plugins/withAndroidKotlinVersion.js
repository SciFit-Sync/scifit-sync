const { withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

module.exports = function withAndroidKotlinVersion(config) {
  return withDangerousMod(config, [
    'android',
    async (config) => {
      const gradlePropertiesPath = path.join(
        config.modRequest.platformProjectRoot,
        'gradle.properties'
      );

      let contents = fs.readFileSync(gradlePropertiesPath, 'utf8');

      if (contents.includes('android.kotlinVersion')) {
        contents = contents.replace(
          /android\.kotlinVersion=.*/g,
          'android.kotlinVersion=1.9.25'
        );
      } else {
        contents += '\nandroid.kotlinVersion=1.9.25\n';
      }

      fs.writeFileSync(gradlePropertiesPath, contents);
      return config;
    },
  ]);
};

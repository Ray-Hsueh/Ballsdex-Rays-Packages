# Adding Custom Package to BallsDex

Follow these steps to add your custom package to BallsDex(we will use broadcast as example):

## Step 1: Create the Custom Directory
1. Navigate to the `ballsdex/packages` directory.
2. Create a new folder named `broadcast`.

### On Linux/Mac:
```sh
mkdir -p ballsdex/packages/broadcast
```

### On Windows:
```sh
mkdir ballsdex\packages\broadcast
```

## Step 2: Download Custom Files
1. Download the necessary files from this repository.
2. Place these files into the `ballsdex/packages/broadcast` directory.


## Step 3: Update Configuration
1. Open the `config.yml` file in your BallsDex project.
2. Add the path to your custom package in the configuration.

```yaml
packages:
    - ballsdex.packages.broadcast
```

## Step 4: Load the Custom Package
1. Ensure your bot is configured to load the custom package.
2. Restart your bot to apply the changes.

## Step 5: Verify Installation
1. Check the bot logs to ensure the custom package is loaded without errors.
2. Use the bot commands to verify the custom functionality is working as expected.

By following these steps, you can successfully add and use the custom package in BallsDex.

gcloud auth application-default login

# Run the cloudbuild.yml file 
gcloud builds submit

gcloud config list

gcloud config set
gcloud config set project PROJECT_ID
gcloud config set compute/region REGION
gcloud config set compute/zone ZONE 

gcloud config configurations create CONFIG_NAME
gcloud config configurations activate CONFIG_NAME
gcloud config configurations delete CONFIG_NAME

gcloud config unset PROPERTY
pipeline {
    agent any
    
    stages {
        stage('Clone Repository') {
            steps {
                echo 'Cloning Flask repository...'
                git branch: 'main', url: 'https://github.com/saadumar0/Flask-App-for-Codacy.git'
            }
        }
        
        stage('Install Dependencies') {
            steps {
                echo 'Installing Python dependencies...'
                sh 'pip install -r requirements.txt'
            }
        }
        
        stage('Run Unit Tests') {
            steps {
                echo 'Running unit tests with pytest...'
                sh 'pytest tests/ -v'
            }
        }
        
        stage('Build Application') {
            steps {
                echo 'Building application...'
                sh 'mkdir -p build'
                sh 'cp -r app build/'
                sh 'cp requirements.txt build/'
                sh 'cp config.py build/'
                echo 'Application packaged successfully'
            }
        }
        
        stage('Deploy Application') {
            steps {
                echo 'Deploying application...'
                sh 'mkdir -p /tmp/flask-deployment'
                sh 'cp -r build/* /tmp/flask-deployment/'
                echo 'Application deployed to /tmp/flask-deployment'
            }
        }
    }
    
    post {
        always {
            echo 'Pipeline execution completed'
        }
        success {
            echo 'Pipeline executed successfully!'
        }
        failure {
            echo 'Pipeline failed - check logs above'
        }
    }
}

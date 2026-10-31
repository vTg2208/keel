pipeline {
  agent any
  options { disableConcurrentBuilds(); buildDiscarder(logRotator(numToKeepStr: '10')) }
  parameters {
    string(name: 'GIT_REPOSITORY', defaultValue: '', description: 'Optional Git URL; blank copies mounted /source')
    booleanParam(name: 'BROKEN_RELEASE', defaultValue: false, description: 'Exercise automatic restoration after a failed validation')
  }
  stages {
    stage('Check out source') {
      steps {
        script {
          if (params.GIT_REPOSITORY?.trim()) {
            git url: params.GIT_REPOSITORY, branch: 'main'
          } else {
            sh "tar -C /source --exclude=.venv --exclude=.local --exclude=.env --exclude=.git --exclude=.terraform --exclude='*.tfstate*' --exclude='*.tfplan' --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache -cf - . | tar -xf -"
          }
        }
        sh '''
          mkdir -p .local
          rm -f .local/smoke-results.json
          cp /source/.env .env
          kind export kubeconfig --name payops --internal --kubeconfig .local/kubeconfig
          python3 -m venv .venv
          .venv/bin/pip install -r requirements.lock
          .venv/bin/pip install -e '.[dev]'
        '''
      }
    }
    stage('Lint and test') {
      steps {
        sh '''
          go test ./...
          go vet ./...
          .venv/bin/python -m payops.lab build
          .venv/bin/python ops.py lint
          .venv/bin/python ops.py test
          node --test tests/frontend.test.mjs
        '''
      }
    }
    stage('Payment recovery discovery') {
      steps { sh '.venv/bin/python -m payops.lab run --seed 42 --budget 8 --require-all' }
    }
    stage('Build release') {
      steps { sh '.venv/bin/python ops.py build --tag build-$BUILD_NUMBER' }
    }
    stage('Load, deploy, smoke, restore on failure') {
      steps {
        script {
          if (params.BROKEN_RELEASE) {
            sh '''
              docker build --build-arg BASE=payops:build-$BUILD_NUMBER -f Dockerfile.broken -t payops:broken-$BUILD_NUMBER .
              docker tag payops:broken-$BUILD_NUMBER payops:build-$BUILD_NUMBER
            '''
          }
        }
        sh '.venv/bin/python ops.py deploy --tag build-$BUILD_NUMBER --monitoring --logging'
      }
    }
  }
  post {
    always {
      archiveArtifacts artifacts: '.local/smoke-results.json,.local/lab-artifacts/**/*', allowEmptyArchive: true
    }
  }
}

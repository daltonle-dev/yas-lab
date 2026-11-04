// NovaMart CI for YAS (decision D4/D5/D6).
// Builds only the images whose inputs changed (ci/plan.py), as ARM images on a
// Graviton agent, and pushes them to ECR with an immutable tag.
// Deploy (helm upgrade) is added later, once the Helm chart exists.
//
// No secrets in this file: the repo is public. AWS access comes from the
// agent's IAM role (instance profile).

pipeline {
  agent { label 'linux-arm64-docker' }

  options {
    timestamps()
    timeout(time: 90, unit: 'MINUTES')
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '20'))
  }

  // Build when GitHub reports a push (webhook). Also declared in the job
  // config (JCasC) so it is active before the first build of each session.
  triggers {
    githubPush()
  }

  parameters {
    booleanParam(name: 'RUN_TESTS', defaultValue: true,  description: 'Run unit tests during the Maven build')
    booleanParam(name: 'FORCE_ALL', defaultValue: false, description: 'Rebuild every image, even if its tag already exists in ECR')
  }

  environment {
    AWS_REGION  = 'ap-south-1'
    JAVA_HOME  = '/opt/tools/jdk25'                        // installed by the agent init script
    TOOLS_PATH = '/opt/tools/jdk25/bin:/opt/tools/maven/bin'
  }

  stages {
    stage('Agent info') {
      steps {
        sh '''
          export PATH="$TOOLS_PATH:$PATH"
          mkdir -p build
          echo "instance type: $(curl -s -H "X-aws-ec2-metadata-token: $(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" http://169.254.169.254/latest/meta-data/instance-type)"
          nproc; free -m; df -h /
          java -version; mvn -version | head -1; docker version --format 'docker {{.Server.Version}}'
          # sample used RAM every 5 s for the whole build (experiment: agent size)
          # JENKINS_NODE_COOKIE: stop Jenkins from killing this background process when the step ends
          JENKINS_NODE_COOKIE=dontKillMe BUILD_ID=dontKillMe nohup sh -c 'while true; do free -m | awk "/Mem:/{print \\$3}"; sleep 5; done' > build/mem-used-mb.log 2>&1 &
          echo $! > build/mem-sampler.pid
        '''
      }
    }

    stage('Plan') {
      steps {
        sh 'FORCE_ALL=${FORCE_ALL} python3 ci/plan.py | tee build/plan.txt'
        script {
          def lines = readFile('build/plan.txt').trim().split('\n').collect { it.split(' ') }
          env.JAVA_BUILD = lines.findAll { it[2] == 'java' && it[4] == 'build' }.collect { it[1] }.join(',')
          env.TO_BUILD   = lines.findAll { it[4] == 'build' }.collect { it[0] }.join(' ')
          echo "Images to build: ${env.TO_BUILD ?: '(none)'}"
        }
      }
    }

    stage('Maven') {
      when { expression { return env.JAVA_BUILD != '' } }
      steps {
        sh '''
          export PATH="$TOOLS_PATH:$PATH"
          SKIP=""; [ "$RUN_TESTS" = "true" ] || SKIP="-DskipTests"
          START=$(date +%s)
          /usr/bin/time -v mvn -B -T 1C -pl "$JAVA_BUILD" -am package $SKIP \
              -Dcheckstyle.skip -Dmaven.javadoc.skip 2> build/mvn-time.txt
          echo "maven: $(( $(date +%s) - START )) s" | tee -a build/timing.txt
          grep "Maximum resident set size" build/mvn-time.txt | tee -a build/timing.txt
        '''
      }
    }

    stage('Images') {
      when { expression { return env.TO_BUILD != '' } }
      steps {
        sh '''
          ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
          REGISTRY="$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com"
          aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"

          while read -r image dir kind tag action inputs; do
            [ "$action" = "build" ] || continue
            ref="$REGISTRY/yas/$image:$tag"
            START=$(date +%s)
            docker build --platform linux/arm64 -t "$ref" "$dir"
            docker push "$ref"
            echo "image $image: $(( $(date +%s) - START )) s" | tee -a build/timing.txt
          done < build/plan.txt
        '''
      }
    }
  }

  post {
    always {
      sh '''
        [ -f build/mem-sampler.pid ] && kill "$(cat build/mem-sampler.pid)" 2>/dev/null || true
        [ -s build/mem-used-mb.log ] && echo "peak used RAM on agent: $(sort -n build/mem-used-mb.log | tail -1) MB" | tee -a build/timing.txt || true
        # image -> tag for every service (built or already in ECR): input for the deploy step later
        [ -f build/plan.txt ] && awk '{print $1, $4}' build/plan.txt > build/image-tags.txt || true
      '''
      archiveArtifacts artifacts: 'build/plan.txt, build/image-tags.txt, build/timing.txt, build/mem-used-mb.log', allowEmptyArchive: true
    }
  }
}

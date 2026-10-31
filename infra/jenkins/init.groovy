import jenkins.model.Jenkins
import hudson.security.HudsonPrivateSecurityRealm
import hudson.security.FullControlOnceLoggedInAuthorizationStrategy
import hudson.model.ParametersDefinitionProperty
import hudson.model.StringParameterDefinition
import hudson.model.BooleanParameterDefinition
import org.jenkinsci.plugins.workflow.job.WorkflowJob
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition

def instance = Jenkins.get()
def password = System.getenv('JENKINS_ADMIN_PASSWORD')
if (!password) { throw new IllegalStateException('JENKINS_ADMIN_PASSWORD is required') }
if (!(instance.securityRealm instanceof HudsonPrivateSecurityRealm)) {
  def realm = new HudsonPrivateSecurityRealm(false)
  realm.createAccount('admin', password)
  instance.setSecurityRealm(realm)
}
def strategy = new FullControlOnceLoggedInAuthorizationStrategy()
strategy.setAllowAnonymousRead(false)
instance.setAuthorizationStrategy(strategy)
instance.setNumExecutors(1)
def job = instance.getItem('PayOps')
if (job == null) {
  job = instance.createProject(WorkflowJob, 'PayOps')
  job.addProperty(new ParametersDefinitionProperty(
    new StringParameterDefinition('GIT_REPOSITORY', '', 'Optional Git URL; blank uses mounted local source'),
    new BooleanParameterDefinition('BROKEN_RELEASE', false, 'Exercise failed release restoration')
  ))
}
job.setDefinition(new CpsFlowDefinition(new File('/source/Jenkinsfile').text, true))
job.save()
instance.save()
